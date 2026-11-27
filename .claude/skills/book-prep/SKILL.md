---
name: book-prep
description: Prepare a purchased ebook or audiobook for the BookOrbit library and the Kindle (KOReader) - rebuild an ebook as a clean EPUB 3 with a correct nested table of contents (parts, chapters, scenes), footnotes KOReader shows in place, stable page numbers and the chosen edition's cover stretched to the Kindle screen; join an audiobook's parts into one tagged m4b with chapters and a square cover; English metadata, a FantLab-checked author spelling and an English folder layout on the NAS. Use whenever the user hands over a book or audiobook file to "prepare", "fix", "process" or "add to the library", says he bought a book, asks for a better cover or table of contents, or mentions LitRes, Goodreads, FantLab, m4b or the BookOrbit library together with a book. Not for PDFs or comics.
---

# Book prep

Turns a store EPUB (usually LitRes, EPUB 2 converted from FB2) into the library copy. Audiobooks follow `references/audiobooks.md`.

All metadata is in English; only the text of the book is Russian. Title, authors, series, description and genres are English (the original title for a translated work; the original-language title for a work with no English edition), and `language` names the language of the text. The scripts do the mechanics; you read the book and make the calls a script cannot: what is a chapter, where scenes break, which ToC entries are noise.

Structure follows the [Standard Ebooks Manual of Style](https://standardebooks.org/manual) where it applies: semantic footnotes with links both ways, `<hr/>` for scene breaks, a nav document with toc, page-list and landmarks. Its English typography rules (quotes, dashes, spelling modernisation) do not apply to Russian text - leave the text itself alone.

## Inputs

- The book file - the user names the path.
- The Goodreads page of the edition whose cover he wants. He picks it; if he did not, ask for the link. Do not choose an edition for him.

## 1. Identify the book on FantLab

```sh
scripts/fantlab.py search "<title> <author>"
scripts/fantlab.py work <work_id>
```

FantLab is the source of truth for authors, so one author is spelled one way across the library (three spellings of George R. R. Martin is the failure this prevents). From the `work` output take:

- Original author names -> book metadata, folder and file names. A pen name wins over the people behind it: FantLab lists Leviathan Wakes under Daniel Abraham and Ty Franck, the book says James S. A. Corey. Use the spelling the library already has for that author (the folder name): BookOrbit matches authors to Goodreads by name, and a Cyrillic or variant spelling leaves the author without a bio.
- The original title -> metadata title, folder and file name.

If the book is not on FantLab, stop and ask. Never invent a spelling. For a non-English original use the English edition's names (`english_editions` in the output: Liu Cixin, "The Three-Body Problem"); with no English edition, transliterate.

Series names and numbers come from Goodreads, not FantLab - FantLab numbers a book inside its widest cycle (Dune comes out 17th in "Dune Universe", Ender's Game 6th):

```sh
scripts/goodreads.py search "<english title> <author>"
```

Goodreads answers scripts with a bot check (HTTP 202) after a few requests. Then search from the user's signed-in Gidora tab (`gidoractl`): `fetch('/book/auto_complete?format=json&q=<title>')`, keep results whose `author.name` matches, take the most rated; the series and number sit in its `title` as "(Series, #N)". A Russian edition split into volumes (A Dance with Dragons, Fire & Blood) keeps the English book's number with a part suffix: 5.1 and 5.2.

## 2. Read the book

```sh
scripts/inspect_epub.py <book.epub>                 # spine, headings, notes, images, the store's ToC
scripts/inspect_epub.py <book.epub> --file <doc>    # one document as plain text
```

Look for: the real part/chapter hierarchy (store ToCs are often flat or wrongly nested), chapter titles worth keeping ("Глава 14. Название" beats "Глава 14"), the element used for scene breaks (`* * *` may be a paragraph, a `<h5>`, an empty line or an image), the document(s) holding the notes, and front matter (title page, copyright, annotation) that has no place in the ToC.

## 3. Cover

```sh
scripts/cover.py "<goodreads edition url>" <work>/cover.jpg
```

It tries Goodreads, the publisher (Penguin Random House serves print TIFFs) and Amazon for that edition and keeps the biggest image, then stretches it to 1236x1648, the Paperwhite 5 screen. Stretch, never crop (it cuts the title) and never pad (on a picture the padding is the same bars the stretch removes).

Then make the grid cover: BookOrbit draws book cards at 2:3, so a 3:4 Kindle cover would be cropped at the sides. Squeeze the same image back to 2:3 (`sips -z 1648 1099`) and upload it to the book's ebook slot after step 7 (`POST /api/v1/books/<id>/cover?medium=ebook`, multipart). The library has `fileWriteWriteCover` off, so this upload never reaches the EPUB and the Kindle keeps its own cover.

It also prints the edition's identifiers (`edition`): ISBN-13, ISBN-10, Goodreads, Amazon and Open Library ids. They go into the plan's metadata as they are - the English edition is the one to link to; BookOrbit counts them toward its metadata score. Google Books answers without a key only until its shared daily quota runs out, so its id is often missing; leave it out rather than retrying.

Show candidates to the user as a page he can click (an Artifact with the `db` capability storing his pick), never as a picture of a contact sheet to describe in chat - he does not see images you read yourself. Two things to raise with him before going on: `"upscaled": true` (the best source is narrower than the screen), and publisher text that looks like an ad sticker ("now a Netflix series", award badges). Text set as part of the design, like a "New York Times bestseller" line in the cover's own type, is fine.

## 4. Write the plan

Start from the draft, then review it against what step 2 found:

```sh
scripts/auto_plan.py <book.epub> <fantlab_work_id> <plan.json>
```

It nests chapters under parts, drops the title, service and `* * *` entries, points ToC links whose anchor does not exist at the file instead, finds the notes documents and the scene breaks, and fills the metadata from FantLab. It prints what it decided; read `toc_top`, `dropped` and `retargeted` before building. Then set the title, authors and series in English from step 1 by hand - the draft takes FantLab's Russian ones. Description and genres come from the Goodreads edition (`GET /api/v1/metadata-fetch/lookup?provider=goodreads&id=<id>` through BookOrbit, or the book page's `__NEXT_DATA__` from the Gidora tab when Goodreads blocks the server): drop paragraphs about other editions, covers, bonuses, reading order and marketing; drop the genres Fiction, Audiobook, Book Club and place names; keep three. Some edition ids carry a description in another language - then take the description of the most-rated English edition.

The schema is in the docstring of `scripts/build_epub.py`. The parts that need judgment:

- `toc`: nested `{title, target, children}`. Parts hold their chapters. Drop the repeated book title, the annotation, copyright, "Сноски"/"Примечания" and other service entries. Targets are `file#id` of the heading; take ids from the store ToC or the documents.
- `scene_break_xpath`: XPath (namespace prefix `h`) matching the break elements; each becomes `<hr class="scene-break"/>`. With `scene_toc: true` every chapter with breaks gets children "N.1", "N.2", ..., so KOReader shows pages left in the scene. Omit both when the book has no scenes.
- `notes.files`: the documents holding notes. Every link into them becomes an EPUB 3 noteref (`[N]`, tappable), the note moves to the end of the chapter that first cites it as `<aside epub:type="footnote">`, and the notes document leaves the spine. KOReader then shows notes at the foot of the page ("In-page EPUB footnotes" style tweak, on on the Kindle).
- `metadata`: names per step 1, `language` from the book (a Belarusian text is `be`), `file_as` as "Surname, Name" (Chinese names keep their order: "Liu, Cixin"), `source` = the FantLab work URL, plus `isbn`, `isbn10` and `identifiers` from the cover step. `source` also seeds the book's identifier, so a rebuilt book keeps the same id and its reading progress. The page count BookOrbit shows is the page-list the build makes.
- `drop_xpath`: only for real junk the ToC fix does not cover (a store promo page, a duplicate title block).

## 5. Build and validate

```sh
scripts/build_epub.py <book.epub> <plan.json> <cover.jpg> <out.epub>
epubcheck <out.epub>
```

The build prints what it did: notes moved, scene breaks, pages (one per 1800 characters, so page numbers do not move with the font size). `missing_notes` must be empty. epubcheck must report 0 errors and 0 warnings; fix the plan or the script, never ship around a finding.

## 6. Place it in the library

```
/mnt/nas/media/bookorbit/library/<Author>/<Series>/<NN - Title>/<Title>.epub
/mnt/nas/media/bookorbit/library/<Author>/<Title>/<Title>.epub          (no series)
```

English names from FantLab, two-digit position in the series. One folder is one book: an audiobook of the same book goes into the same folder, which is what lets BookOrbit build a read-along. BookOrbit's own file naming pattern stays empty.

## 7. Let BookOrbit read it, then lock it

BookOrbit watches the folder over NFS on alpha, and NFS does not report files written from another machine, so a book placed from the Mac is not noticed. Start a scan through the API from the user's signed-in Gidora tab (`gidoractl`, its skill has the tab rules; the library id is 1):

```js
await fetch('/api/v1/scanner/libraries/1/scan', { method: 'POST', credentials: 'include', headers: { 'content-type': 'application/json' }, body: '{}' })
```

A scan only looks into folders whose modification time changed. A new book folder qualifies; a rebuilt file overwritten in place does not, so first create and delete a file in its folder (on alpha, `touch <dir>/.bump && rm <dir>/.bump`).

Then find the book (`POST /api/v1/libraries/1/books` with `{}` lists them) and lock the fields this skill owns, so a metadata refresh from Goodreads or another provider cannot replace them:

```js
await fetch(`/api/v1/books/${id}/metadata-locks`, { method: 'PATCH', credentials: 'include', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ lockedFields: ['title', 'authors', 'description', 'publisher', 'publishedYear', 'language', 'pageCount', 'seriesName', 'seriesIndex', 'isbn13', 'isbn10', 'genres', 'goodreadsId', 'amazonId', 'openLibraryId'] }) })
```

A locked field also ignores the file on later scans: after a rebuild that changes one of them, unlock it first. `communityRating` stays unlocked - BookOrbit takes community ratings only from providers, never from the file.

The library has EPUB file writes on: BookOrbit writes metadata edits back into the OPF. Its writer adds two known epubcheck errors (`opf:scheme` on identifiers, milliseconds in `dcterms:modified`); readers ignore them. Run epubcheck on the build before placing it, not on the library copy afterwards.

Leave the source file where it was. Report the folder, the build counts, the epubcheck result and the BookOrbit metadata score in a few lines.

## Example

Dungeon Crawler Carl from LitRes: the store ToC put "Глава 2"-"Глава 26" next to "Часть 1" instead of inside it; scene breaks were `<h5>* * *</h5>`; 165 translator notes sat in `contentnotes0.html` with LitRes's own "Вернуться" link in each (dropped by the build). The Goodreads edition 9780593820247 gave a 2450x3700 print TIFF at Penguin Random House. Result: `Matt Dinniman/Dungeon Crawler Carl/01 - Dungeon Crawler Carl/Dungeon Crawler Carl.epub`, 58 ToC entries, 392 pages, epubcheck clean, BookOrbit metadata score 91%.

Verity from LitRes: a thriller with Verity's manuscript chapters interleaved with the main ones; the store ToC already nested them, so the draft plan needed only English metadata. The Goodreads edition gave its cover through Amazon by ISBN-10 at 1711x2560. Result: `Colleen Hoover/Verity/Verity.epub`, 249 pages, epubcheck clean, score 83%, the author enriched with a bio and photo on import.
