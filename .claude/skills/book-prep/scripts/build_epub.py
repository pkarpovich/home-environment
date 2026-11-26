#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["lxml>=5"]
# ///
"""Rebuild an EPUB as EPUB 3 from the source book and a plan written after reading it.

usage: build_epub.py <source.epub> <plan.json> <cover.jpg> <out.epub>

The plan is JSON:
{
  "metadata": {
    "title": "...", "language": "ru", "date": "2021", "description": "...",
    "authors": [{"name": "Мэтт Динниман", "file_as": "Динниман, Мэтт"}],
    "series": {"name": "Карл — обходчик подземелий", "index": 1},
    "source": "https://fantlab.ru/work1807247",
    "isbn": "9780593820247"                      (optional, the edition the cover came from)
  },
  "toc": [{"title": "Часть 1", "target": "content1.html#id", "children": [...]}],
  "bodymatter": "content0.html#id",
  "notes": {"files": ["contentnotes0.html"]},   (documents holding the notes; dropped from the spine)
  "scene_break_xpath": "//h:h5[normalize-space()='* * *']",   (optional, h = XHTML namespace)
  "scene_toc": true,                             (optional, a ToC child per scene)
  "drop_xpath": ["..."],                         (optional, elements to delete, same namespace)
  "chars_per_page": 1800
}
"""
import copy
import datetime
import json
import re
import sys
import uuid
import zipfile
from posixpath import dirname, join, normpath, relpath

from lxml import etree

XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
NCX = "http://www.daisy.org/z3986/2005/ncx/"
NS = {"h": XHTML, "opf": OPF, "dc": DC}
H = "{%s}" % XHTML
EP = "{%s}" % EPUB
BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "dd", "dt", "td"}
COVER_HREF = "images/cover.jpg"


def local(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def text_len(el):
    return len(re.sub(r"\s+", " ", "".join(el.itertext())).strip())


class Book:
    def __init__(self, src):
        self.zip = zipfile.ZipFile(src)
        self.opf_path = re.search(rb'full-path="([^"]+)"', self.zip.read("META-INF/container.xml")).group(1).decode()
        self.base = dirname(self.opf_path)
        self.opf = etree.fromstring(self.zip.read(self.opf_path))
        self.manifest = {i.get("id"): i for i in self.opf.find("opf:manifest", NS)}
        by_id = self.manifest
        self.spine = [by_id[r.get("idref")].get("href") for r in self.opf.find("opf:spine", NS)]
        self.docs = {}
        parser = etree.XMLParser(recover=True, resolve_entities=False, remove_blank_text=False)
        for href in self.spine:
            raw = self.zip.read(self.path(href))
            self.docs[href] = to_xhtml5(etree.fromstring(raw, parser))

    def path(self, href):
        return normpath(join(self.base, href))


def to_xhtml5(root):
    """A fresh <html> with the epub namespace declared; lxml cannot add one to an existing root."""
    html = etree.Element(H + "html", nsmap={None: XHTML, "epub": EPUB})
    html.set("lang", "ru")
    html.set("{http://www.w3.org/XML/1998/namespace}lang", "ru")
    for child in root:
        if not isinstance(child.tag, str):
            continue
        if not child.tag.startswith(H):
            child.tag = H + local(child)
        html.append(child)
    for el in html.iter():
        if isinstance(el.tag, str) and not el.tag.startswith("{"):
            el.tag = H + el.tag
    head = html.find(H + "head")
    if head is not None:
        for meta in head.findall(H + "meta"):
            if meta.get("http-equiv", "").lower() == "content-type" or meta.get("charset"):
                head.remove(meta)
        charset = etree.Element(H + "meta", charset="utf-8")
        head.insert(0, charset)
    return html


def body(doc):
    return doc.find(H + "body")


def element_by_id(doc, frag):
    found = doc.xpath("//*[@id=$i]", i=frag)
    return found[0] if found else None


def note_label(ref):
    digits = re.findall(r"\d+", "".join(ref.itertext()))
    return f"[{digits[0]}]" if digits else "[*]"


def move_notes(book, plan, report):
    note_files = set(plan.get("notes", {}).get("files", []))
    if not note_files:
        return
    placed = {}
    for href in book.spine:
        if href in note_files:
            continue
        doc = book.docs[href]
        asides = []
        for ref in doc.xpath("//h:a[@href]", namespaces=NS):
            target, _, frag = ref.get("href").partition("#")
            if target not in note_files or not frag:
                continue
            note = element_by_id(book.docs[target], frag)
            if note is None:
                report["missing_notes"].append(frag)
                continue
            if not ref.get("id"):
                ref.set("id", f"ref-{frag}")
            label = note_label(ref)
            for child in list(ref):
                ref.remove(child)
            ref.text = label
            ref.set(EP + "type", "noteref")
            ref.set("role", "doc-noteref")
            if frag in placed:
                ref.set("href", f"{relpath(placed[frag], dirname(href) or '.')}#{frag}")
                continue
            ref.set("href", f"#{frag}")
            asides.append(build_aside(note, frag, ref.get("id"), label))
            placed[frag] = href
        if asides:
            section = etree.SubElement(body(doc), H + "section")
            section.set(EP + "type", "footnotes")
            section.set("class", "footnotes")
            section.extend(asides)
    report["notes_moved"] = len(placed)


def is_return_link(block):
    """The store's own "back to text" paragraph: one short link and nothing else."""
    links = block.xpath(".//h:a", namespaces=NS)
    return len(links) == 1 and text_len(block) == text_len(links[0]) and text_len(block) < 25


def build_aside(note, frag, back_id, label):
    aside = etree.Element(H + "aside")
    aside.set("id", frag)
    aside.set(EP + "type", "footnote")
    aside.set("role", "doc-footnote")
    paragraphs = [copy.deepcopy(c) for c in note if isinstance(c.tag, str) and local(c) in BLOCKS - {"h1", "h2", "h3", "h4", "h5", "h6"}]
    paragraphs = [p for p in paragraphs if not is_return_link(p)]
    if not paragraphs:
        p = etree.Element(H + "p")
        p.text = " ".join("".join(note.itertext()).split())
        paragraphs = [p]
    for p in paragraphs:
        p.attrib.pop("class", None)
        aside.append(p)
    last = paragraphs[-1]
    back = etree.SubElement(last, H + "a")
    back.set("href", f"#{back_id}")
    back.set("role", "doc-backlink")
    back.text = "↩"
    back.tail = None
    lead = etree.Element(H + "span")
    lead.set("class", "note-label")
    lead.text = label + " "
    paragraphs[0].insert(0, lead)
    lead.tail = paragraphs[0].text
    paragraphs[0].text = None
    return aside


def apply_drops(book, plan, report):
    for xpath in plan.get("drop_xpath", []):
        for href in book.spine:
            for el in book.docs[href].xpath(xpath, namespaces=NS):
                el.getparent().remove(el)
                report["dropped"] += 1


def scene_breaks(book, plan, report):
    xpath = plan.get("scene_break_xpath")
    breaks = []
    if not xpath:
        return breaks
    for href in book.spine:
        for n, el in enumerate(book.docs[href].xpath(xpath, namespaces=NS)):
            hr = etree.Element(H + "hr")
            hr.set("class", "scene-break")
            hr.set("id", f"scene-{len(breaks) + 1}")
            hr.tail = el.tail
            el.getparent().replace(el, hr)
            breaks.append((href, hr))
    report["scene_breaks"] = len(breaks)
    return breaks


def order_key(book, href, el):
    doc = book.docs[href]
    return (book.spine.index(href), list(doc.iter()).index(el))


def resolve(book, target):
    href, _, frag = target.partition("#")
    doc = book.docs[href]
    el = element_by_id(doc, frag) if frag else body(doc)
    if el is None:
        raise SystemExit(f"toc target not found: {target}")
    return href, el


def add_scene_entries(book, toc, breaks):
    leaves = []

    def walk(items):
        for item in items:
            if item.get("children"):
                walk(item["children"])
            else:
                leaves.append(item)

    walk(toc)
    keyed = sorted(((order_key(book, *resolve(book, leaf["target"])), leaf) for leaf in leaves), key=lambda x: x[0])
    for href, hr in breaks:
        key = order_key(book, href, hr)
        owner = None
        for leaf_key, leaf in keyed:
            if leaf_key <= key:
                owner = leaf
        if owner is None:
            continue
        number = re.findall(r"\d+", owner["title"])
        prefix = f"{number[0]}." if number else "· "
        scenes = owner.setdefault("children", [])
        if not scenes:
            scenes.append({"title": f"{prefix}1", "target": owner["target"]})
        scenes.append({"title": f"{prefix}{len(scenes) + 1}", "target": f"{href}#{hr.get('id')}"})


def page_breaks(book, plan, skip, report):
    per_page = plan.get("chars_per_page", 1800)
    count, page, pages = 0, 1, []
    for href in book.spine:
        if href in skip:
            continue
        for el in body(book.docs[href]).iter():
            if not isinstance(el.tag, str) or local(el) not in BLOCKS:
                continue
            if any(local(a) == "aside" for a in el.iterancestors()):
                continue
            if any(isinstance(c.tag, str) and local(c) in BLOCKS for c in el):
                continue
            if count >= (page - 1) * per_page:
                marker = etree.Element(H + "span")
                marker.set("id", f"page-{page}")
                marker.set(EP + "type", "pagebreak")
                marker.set("role", "doc-pagebreak")
                marker.set("aria-label", str(page))
                marker.tail = el.text
                el.text = None
                el.insert(0, marker)
                pages.append((page, f"{href}#page-{page}"))
                page += 1
            count += text_len(el)
    report["pages"] = len(pages)
    return pages


def nav_doc(toc, pages, bodymatter, title):
    html = etree.Element(H + "html", nsmap={None: XHTML, "epub": EPUB})
    html.set("lang", "ru")
    head = etree.SubElement(html, H + "head")
    etree.SubElement(head, H + "title").text = title
    b = etree.SubElement(html, H + "body")

    def ol(parent, items):
        lst = etree.SubElement(parent, H + "ol")
        for item in items:
            li = etree.SubElement(lst, H + "li")
            a = etree.SubElement(li, H + "a", href=item["target"])
            a.text = item["title"]
            if item.get("children"):
                ol(li, item["children"])

    nav = etree.SubElement(b, H + "nav", id="toc")
    nav.set(EP + "type", "toc")
    etree.SubElement(nav, H + "h2").text = "Оглавление"
    ol(nav, toc)
    if pages:
        pl = etree.SubElement(b, H + "nav", id="page-list", hidden="")
        pl.set(EP + "type", "page-list")
        ol(pl, [{"title": str(n), "target": t} for n, t in pages])
    lm = etree.SubElement(b, H + "nav", id="landmarks", hidden="")
    lm.set(EP + "type", "landmarks")
    lst = etree.SubElement(lm, H + "ol")
    for kind, target, label in (("cover", "cover.xhtml", "Обложка"), ("bodymatter", bodymatter, "Начало")):
        a = etree.SubElement(etree.SubElement(lst, H + "li"), H + "a", href=target)
        a.set(EP + "type", kind)
        a.text = label
    return html


def ncx_doc(toc, uid, title):
    ncx = etree.Element("{%s}ncx" % NCX, nsmap={None: NCX}, version="2005-1")
    head = etree.SubElement(ncx, "{%s}head" % NCX)
    etree.SubElement(head, "{%s}meta" % NCX, name="dtb:uid", content=uid)
    etree.SubElement(etree.SubElement(ncx, "{%s}docTitle" % NCX), "{%s}text" % NCX).text = title
    nav_map = etree.SubElement(ncx, "{%s}navMap" % NCX)
    counter = [0]
    orders = {}

    def add(parent, items):
        for item in items:
            counter[0] += 1
            if item["target"] not in orders:
                orders[item["target"]] = len(orders) + 1
            point = etree.SubElement(parent, "{%s}navPoint" % NCX, id=f"np-{counter[0]}", playOrder=str(orders[item["target"]]))
            etree.SubElement(etree.SubElement(point, "{%s}navLabel" % NCX), "{%s}text" % NCX).text = item["title"]
            etree.SubElement(point, "{%s}content" % NCX, src=item["target"])
            add(point, item.get("children", []))

    add(nav_map, toc)
    return ncx


def cover_doc(alt):
    html = etree.Element(H + "html", nsmap={None: XHTML, "epub": EPUB})
    html.set("lang", "ru")
    head = etree.SubElement(html, H + "head")
    etree.SubElement(head, H + "title").text = alt
    etree.SubElement(head, H + "style").text = "body{margin:0;padding:0;text-align:center}img{height:100%;max-width:100%}"
    b = etree.SubElement(html, H + "body")
    b.set(EP + "type", "cover")
    img = etree.SubElement(b, H + "img", src=COVER_HREF, alt=alt)
    img.set(EP + "type", "cover-image")
    return html


def package(book, plan, keep, spine, uid):
    meta = plan["metadata"]
    pkg = etree.Element("{%s}package" % OPF, nsmap={None: OPF, "dc": DC}, version="3.0")
    pkg.set("unique-identifier", "pub-id")
    pkg.set("{http://www.w3.org/XML/1998/namespace}lang", meta.get("language", "ru"))
    md = etree.SubElement(pkg, "{%s}metadata" % OPF)

    def dc(tag, text, **attrs):
        el = etree.SubElement(md, "{%s}%s" % (DC, tag), **attrs)
        el.text = text
        return el

    def prop(name, text, **attrs):
        el = etree.SubElement(md, "{%s}meta" % OPF, property=name, **attrs)
        el.text = text

    dc("identifier", uid, id="pub-id")
    if meta.get("isbn"):
        dc("identifier", f"urn:isbn:{meta['isbn']}", id="isbn")
    dc("title", meta["title"])
    for n, author in enumerate(meta["authors"], 1):
        dc("creator", author["name"], id=f"aut{n}")
        prop("file-as", author["file_as"], refines=f"#aut{n}")
        prop("role", "aut", refines=f"#aut{n}", scheme="marc:relators")
    dc("language", meta.get("language", "ru"))
    for key in ("date", "description", "publisher", "source"):
        if meta.get(key):
            dc(key, meta[key])
    for subject in meta.get("subjects", []):
        dc("subject", subject)
    if meta.get("series"):
        prop("belongs-to-collection", meta["series"]["name"], id="series")
        prop("collection-type", "series", refines="#series")
        prop("group-position", str(meta["series"]["index"]), refines="#series")
        etree.SubElement(md, "{%s}meta" % OPF, name="calibre:series", content=meta["series"]["name"])
        etree.SubElement(md, "{%s}meta" % OPF, name="calibre:series_index", content=str(meta["series"]["index"]))
    etree.SubElement(md, "{%s}meta" % OPF, name="cover", content="cover-image")
    prop("dcterms:modified", datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    manifest = etree.SubElement(pkg, "{%s}manifest" % OPF)
    for item_id, href, mtype, props in keep:
        el = etree.SubElement(manifest, "{%s}item" % OPF, id=item_id, href=href)
        el.set("media-type", mtype)
        if props:
            el.set("properties", props)
    sp = etree.SubElement(pkg, "{%s}spine" % OPF, toc="ncx")
    for item_id in spine:
        etree.SubElement(sp, "{%s}itemref" % OPF, idref=item_id)
    return pkg


def serialize_xhtml(doc):
    body_bytes = etree.tostring(doc, encoding="unicode")
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n' + body_bytes).encode("utf-8")


def main():
    src, plan_path, cover_path, out = sys.argv[1:5]
    plan = json.load(open(plan_path, encoding="utf-8"))
    book = Book(src)
    report = {"missing_notes": [], "dropped": 0}
    note_files = set(plan.get("notes", {}).get("files", []))
    old_cover_pages = {h for h in book.spine if re.search(r"cover|titlepage", h, re.I) and len(book.docs[h].xpath("//h:img", namespaces=NS)) >= 1 and text_len(body(book.docs[h])) < 50}

    apply_drops(book, plan, report)
    move_notes(book, plan, report)
    breaks = scene_breaks(book, plan, report)
    toc = plan["toc"]
    if plan.get("scene_toc") and breaks:
        add_scene_entries(book, toc, breaks)
    pages = page_breaks(book, plan, note_files | old_cover_pages, report)

    uid = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, plan['metadata']['source'])}"
    title = plan["metadata"]["title"]
    keep, spine_ids, written = [], [], {}
    keep.append(("cover-page", "cover.xhtml", "application/xhtml+xml", None))
    spine_ids.append("cover-page")
    written["cover.xhtml"] = serialize_xhtml(cover_doc(title))
    keep.append(("cover-image", COVER_HREF, "image/jpeg", "cover-image"))
    written[COVER_HREF] = open(cover_path, "rb").read()
    keep.append(("nav", "nav.xhtml", "application/xhtml+xml", "nav"))
    written["nav.xhtml"] = serialize_xhtml(nav_doc(toc, pages, plan["bodymatter"], title))
    keep.append(("ncx", "toc.ncx", "application/x-dtbncx+xml", None))
    written["toc.ncx"] = etree.tostring(ncx_doc(toc, uid, title), xml_declaration=True, encoding="utf-8")

    used_ids = {k[0] for k in keep}
    href_to_id = {}
    for n, href in enumerate(book.spine):
        if href in note_files or href in old_cover_pages:
            continue
        item_id = f"doc{n}"
        href_to_id[href] = item_id
        keep.append((item_id, href, "application/xhtml+xml", None))
        spine_ids.append(item_id)
        written[href] = serialize_xhtml(book.docs[href])
        used_ids.add(item_id)

    referenced = "".join(v.decode("utf-8", "replace") for k, v in written.items() if k.endswith((".html", ".xhtml", ".htm")))
    for item in book.manifest.values():
        href, mtype = item.get("href"), item.get("media-type")
        if href in book.spine or mtype in ("application/x-dtbncx+xml",) or href in written:
            continue
        if mtype.startswith("image/") and href.split("/")[-1] not in referenced:
            continue
        item_id = item.get("id") if item.get("id") not in used_ids else f"res-{len(keep)}"
        used_ids.add(item_id)
        keep.append((item_id, href, mtype, None))
        written[href] = book.zip.read(book.path(href))

    pkg = package(book, plan, keep, spine_ids, uid)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0" encoding="utf-8"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
                   compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", etree.tostring(pkg, xml_declaration=True, encoding="utf-8", pretty_print=True), compress_type=zipfile.ZIP_DEFLATED)
        for href, data in written.items():
            z.writestr(f"OEBPS/{href}", data, compress_type=zipfile.ZIP_DEFLATED)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
