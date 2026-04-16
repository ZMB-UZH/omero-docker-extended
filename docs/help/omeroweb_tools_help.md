# Enhanced Search Help

Enhanced Search helps you find images from one compact page. It can search
OMERO's normal index, your opt-in universal metadata index, or both together.

## Search

1. Type a word, number, image name fragment, project name, dataset name, tag, or
   metadata value.
2. Choose an `Indexed scope`.
3. Optionally add a start date, an end date, or both.
4. Click `Search`.

Search terms use prefix matching. For example, `Ze` can match `Zeiss`, and
`488` can match values beginning with `488`. Quoted text searches as a phrase.

## Indexed Scope

- `OMERO index`: searches OMERO's built-in searchable content.
- `Universal metadata index`: searches the extra metadata index for images in
  your account.
- `All searchable sources`: searches both and merges duplicate image results.

## Universal Metadata Index

Enable `Universal metadata indexing` when you want Enhanced Search to include
metadata that OMERO's normal search does not cover. The setting is per user.

Click `Refresh index` to update your metadata index. The button is disabled
while a refresh is already running.

## Results

Results show a preview, image name, project/dataset context, acquisition
metadata, and channels when available. Click an image, project, or dataset link
to open it in OMERO.web.

## Saved Search Queries

Use `Save current search as...` to store searches you run often. Saved searches
belong to your user account.

## Clear

Click `Clear` to empty the search box, date fields, and current results without
leaving the page.

## If Results Look Missing

- Check that you selected the intended `Indexed scope`.
- Refresh your universal metadata index after new imports or metadata changes.
- Use fewer terms if the query is too narrow.
- Confirm that you still have OMERO permission to view the image.
