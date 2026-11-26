---
name: book-prep
description: Prepare a purchased ebook for the BookOrbit library and the Kindle (KOReader) - rebuild it as a clean EPUB 3 with a correct nested table of contents (parts, chapters, scenes), footnotes KOReader shows in place, stable page numbers, the cover of the edition chosen on Goodreads at full resolution stretched to the Kindle screen, metadata from FantLab, and an English folder layout in the library on the NAS. Use whenever the user hands over a book file to "prepare", "fix", "process" or "add to the library", says he bought a book, asks for a better cover or table of contents, or mentions LitRes, Goodreads covers, FantLab or the BookOrbit library together with a book. Not for audiobooks alone, PDFs or comics.
---

# Book prep

Turns a store EPUB (usually LitRes, EPUB 2 converted from FB2) into the library copy. The scripts do the mechanics; you read the book and make the calls a script cannot: what is a chapter, where scenes break, which ToC entries are noise.

Structure follows the [Standard Ebooks Manual of Style](https://standardebooks.org/manual) where it applies: semantic footnotes with links both ways, `<hr/>` for scene breaks, a nav document with toc, page-list and landmarks. Its English typography rules (quotes, dashes, spelling modernisation) do not apply to Russian text - leave the text itself alone.

## Inputs

- The book file - the user names the path.
- The Goodreads page of the edition whose cover he wants. He picks it; if he did not, ask for the link. Do not choose an edition for him.

## 1. Identify the book on FantLab

```sh
scripts/fantlab.py search "<title> <author>"
scripts/fantlab.py work <work_id>
```

FantLab is the source of truth for names, so one author is spelled one way across the library (three spellings of George R. R. Martin is the failure this prevents). From the `work` output take:

- Russian title and author names -> book metadata (what BookOrbit and KOReader show).
- Original names -> folder and file names.
- Cycle and position -> series; the cycle's original name comes from `work <cycle_id>` or from the Goodreads series line.

If the book is not on FantLab, stop and ask. Never invent a spelling. For a non-English original use the English edition's names (Liu Cixin, "The Three-Body Problem"); with no English edition, transliterate.

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

It also prints the edition's identifiers (`edition`): ISBN-13, ISBN-10, Goodreads, Amazon and Open Library ids. They go into the plan's metadata as they are - the English edition is the one to link to; BookOrbit counts them toward its metadata score. Google Books answers without a key only until its shared daily quota runs out, so its id is often missing; leave it out rather than retrying.

Open the result for the user (`open -a Preview <file>`) - he does not see images you read yourself. Two things to raise with him before going on: `"upscaled": true` (the best source is narrower than the screen), and publisher text that looks like an ad sticker ("now a Netflix series", award badges). Text set as part of the design, like a "New York Times bestseller" line in the cover's own type, is fine.

## 4. Write the plan

A JSON file in the session scratchpad; the schema is in the docstring of `scripts/build_epub.py`. The parts that need judgment:

- `toc`: nested `{title, target, children}`. Parts hold their chapters. Drop the repeated book title, the annotation, copyright, "Сноски"/"Примечания" and other service entries. Targets are `file#id` of the heading; take ids from the store ToC or the documents.
- `scene_break_xpath`: XPath (namespace prefix `h`) matching the break elements; each becomes `<hr class="scene-break"/>`. With `scene_toc: true` every chapter with breaks gets children "N.1", "N.2", ..., so KOReader shows pages left in the scene. Omit both when the book has no scenes.
- `notes.files`: the documents holding notes. Every link into them becomes an EPUB 3 noteref (`[N]`, tappable), the note moves to the end of the chapter that first cites it as `<aside epub:type="footnote">`, and the notes document leaves the spine. KOReader then shows notes at the foot of the page ("In-page EPUB footnotes" style tweak, on on the Kindle).
- `metadata`: Russian names from FantLab, `file_as` as "Фамилия, Имя", `source` = the FantLab work URL, plus `isbn`, `isbn10` and `identifiers` from the cover step. `source` also seeds the book's identifier, so a rebuilt book keeps the same id and its reading progress. The page count BookOrbit shows is the page-list the build makes.
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

English names from FantLab, two-digit position in the series. One folder is one book: an audiobook of the same book goes into the same folder later, which is what lets BookOrbit build a read-along. BookOrbit's own file naming pattern stays empty, or it would rename everything back to the Russian metadata title.

## 7. Let BookOrbit read it, then lock it

BookOrbit watches the folder over NFS on alpha, and NFS does not report files written from another machine, so a book placed from the Mac is not noticed. Start a scan through the API from the user's signed-in Gidora tab (`gidoractl`, its skill has the tab rules; the library id is 1):

```js
await fetch('/api/v1/scanner/libraries/1/scan', { method: 'POST', credentials: 'include', headers: { 'content-type': 'application/json' }, body: '{}' })
```

A scan only looks into folders whose modification time changed. A new book folder qualifies; a rebuilt file overwritten in place does not, so first create and delete a file in its folder (on alpha, `touch <dir>/.bump && rm <dir>/.bump`).

Then find the book (`POST /api/v1/libraries/1/books` with `{}` lists them) and lock the fields this skill owns, so a metadata refresh from Goodreads or another provider cannot replace the Russian names:

```js
await fetch(`/api/v1/books/${id}/metadata-locks`, { method: 'PATCH', credentials: 'include', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ lockedFields: ['title', 'authors', 'description', 'publisher', 'publishedYear', 'language', 'pageCount', 'seriesName', 'seriesIndex', 'isbn13', 'isbn10', 'genres', 'goodreadsId', 'amazonId', 'openLibraryId'] }) })
```

A locked field also ignores the file on later scans: after a rebuild that changes one of them, unlock it first. `communityRating` stays unlocked - BookOrbit takes community ratings only from providers, never from the file.

Leave the source file where it was. Report the folder, the build counts, the epubcheck result and the BookOrbit metadata score in a few lines.

## Example

Dungeon Crawler Carl from LitRes: the store ToC put "Глава 2"-"Глава 26" next to "Часть 1" instead of inside it; scene breaks were `<h5>* * *</h5>`; 165 translator notes sat in `contentnotes0.html` with LitRes's own "Вернуться" link in each (dropped by the build). The Goodreads edition 9780593820247 gave a 2450x3700 print TIFF at Penguin Random House. Result: `Matt Dinniman/Dungeon Crawler Carl/01 - Dungeon Crawler Carl/Dungeon Crawler Carl.epub`, 58 ToC entries, 392 pages, epubcheck clean, BookOrbit metadata score 91%.
