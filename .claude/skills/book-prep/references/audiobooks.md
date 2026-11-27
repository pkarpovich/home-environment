# Audiobooks

The target is one m4b per book, in the same folder as the book's EPUB, named `<Title>.m4b`: all chapters, English tags and a square cover. One file per book is what Prologue, BookOrbit and Plex expect, and the shared folder is what lets BookOrbit pair the text and the audio.

## Sources

The audiobooks arrive as Audiobook Builder output in Plex's folder on the NAS (`/volume2/media/audiobooks/<Russian title>/`), often split into parts of about 12 hours. Leave that folder alone: copy into the library, never move.

## Metadata

The same English rules as for EPUBs (SKILL.md step 1): title, authors and series as the library already spells them, description and genres from BookOrbit's book record. Tag the audio language as `rus`.

The narrator is rarely in the tags. Find the LitRes audio edition whose duration matches the files (`scripts/litres_audio.py search`, then `get` on each candidate; a match is within 2-3 %), or read it off the existing cover ("Читает ..."). Write it in Latin letters (Игорь Князев -> Igor Knyazev). Leave it empty rather than guess.

## Cover

Square, at least 1500 px. BookOrbit draws a book that has only audio as a square card, and players show a square. Candidates, best first:

- the poster the user set in Plex (`/library/metadata/<ratingKey>/thumb` with the Plex token from alpha's `.env`) - this is the cover he already chose, but often small;
- r/AudiobookCovers custom covers, searched from a Gidora tab (the JSON API answers 403; read the search page and the post pages, full size at `https://i.redd.it/<id>.<ext>`);
- LitRes `https://cdn.litres.ru/pub/c/cover_max1500/<art id>.jpg`; Bookmate `...-original.jpeg` (3000 px); Audible `api.audible.com/1.0/catalog/products?...&image_sizes=2400`; Apple Books artwork with `3000x3000bb`.

Store covers are often swapped for film or series tie-ins (HBO, Netflix, Apple TV+, "only from Audible"): reject those. Put the candidates on a page the user clicks (an Artifact with `db` storing the picks) and read the picks back; never ask him to choose from a picture.

## Build

```sh
scripts/build_m4b.py <meta.json> <cover.jpg> <out.m4b> <part1.m4b> [<part2.m4b> ...]
```

Stream copy, so the audio is bit for bit the same. Each part's chapters move to its offset; generic titles ("Chapter 01") become "Глава 1". Check the printed `chapters` equals `expected_chapters` and `duration_h` equals `parts_h`.

When the book's EPUB is in the folder, name the chapters after it:

```sh
scripts/audio_chapters.py <book.m4b> <book.epub> [--write]
```

It acts only on generic titles, and only when the tracks line up with the EPUB's chapters by count and by each chapter's share of the text against its track's share of the time; otherwise "Глава N" stays. On the first library run it renamed Wool, Project Hail Mary and Shift (a prologue split over two tracks), and left The Three-Body Problem, Altered Carbon and Dust, whose tracks do not follow the book's chapters.

## Placing it

BookOrbit deletes the record of a file that disappeared from a book folder, and listening sessions and audio progress hang off that record with `ON DELETE CASCADE`. So before replacing parts:

1. Back up `reading_sessions` (session_type `listen`) and `audiobook_progress` for the book from `bookorbit-db`.
2. Copy the new m4b in under a temporary name, move the old parts to `/mnt/nas/media/bookorbit/parts-backup/<same path>`, rename the new file.
3. Scan the library (SKILL.md step 7).
4. Re-post the missing sessions to the new file with their original `sessionId` (`POST /api/v1/books/files/<file id>/sessions`) and restore the position (`PATCH /api/v1/books/<id>/audio-progress`; the part's position plus the length of the parts before it).

The library keeps audio file writes off: the tags this skill writes are the source.

A book with audio only has no ebook slot, so BookOrbit shows the audio cover. A cover uploaded to a slot by hand wins over the one a scan extracts, so after changing an m4b cover also upload it to `medium=audio` if that slot was set by hand before.
