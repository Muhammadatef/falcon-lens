#!/bin/zsh
# Import the v2 deck into Keynote and write the .key, a PDF and one PNG per slide.
#
#   submission/build/keynote_v2.sh <deck.pptx> <out.key> <out.pdf|-> <png dir|->
#
# Keynote keeps the builds, the transitions, the speaker notes and the slide links of the .pptx. This script only
# tightens the transition lengths, saves, exports and prints what Keynote holds (one line per slide).
# The document is pinned by its id, never by index or "front document", and only that document is closed, so
# presentations the presenter has open are left alone. `open -a` is used because AppleScript `open` can hang.
set -e
PPTX="$1"; KEY="$2"; PDF="${3:--}"; PNG="${4:--}"
APP="${KEYNOTE_APP:-Keynote Creator Studio}"
NAME="$(basename "$PPTX" .pptx)"
PREV=$(osascript -e "tell application \"$APP\" to return id of every document" 2>/dev/null || true)
rm -rf "$KEY"
open -a "$APP" "$PPTX"
osascript <<EOF
tell application "$APP"
  set prevIds to "$PREV"
  set theId to ""
  repeat 240 times
    try
      set ids to id of every document
      repeat with k from 1 to count of ids
        set anId to (item k of ids) as text
        if prevIds does not contain anId then
          if (name of document id anId) is "$NAME" then set theId to anId
        end if
      end repeat
    end try
    if theId is not "" then exit repeat
    delay 0.5
  end repeat
  if theId is "" then error "the document did not open"
  delay 1
  if (name of document id theId) is not "$NAME" then error "pinned the wrong document"
  set n to count of slides of document id theId
  repeat with i from 1 to n
    set tp to transition properties of slide i of document id theId
    set fx to transition effect of tp
    if fx is push then
      set transition properties of slide i of document id theId to {transition effect:push, transition duration:0.7, transition delay:0, automatic transition:false}
    else if fx is dissolve then
      set transition properties of slide i of document id theId to {transition effect:dissolve, transition duration:0.5, transition delay:0, automatic transition:false}
    end if
  end repeat
  save document id theId in POSIX file "$KEY"
  delay 1
  if "$PDF" is not "-" then export document id theId to POSIX file "$PDF" as PDF with properties {PDF image quality:Best}
  if "$PNG" is not "-" then export document id theId to POSIX file "$PNG" as slide images with properties {image format:PNG, skipped slides:false}
  set out to "keynote: " & n & " slides"
  repeat with i from 1 to n
    set s to slide i of document id theId
    set tp to transition properties of s
    set hasNotes to "notes"
    if (presenter notes of s) is "" then set hasNotes to "NO NOTES"
    set out to out & linefeed & i & " | " & (transition effect of tp as text) & " | " & (transition duration of tp as text) & " s | auto " & (automatic transition of tp as text) & " | " & hasNotes & " | movies " & (count of movies of s)
  end repeat
  close document id theId saving no
  return out
end tell
EOF
