# Filename & Metadata Manager Help

Use this plugin to turn structured filenames into OMERO key-value metadata.
The usual workflow has two pages: choose what to process, then preview and
apply the parsed metadata.

## Select and Prepare

1. Choose a project.
2. Select one or more datasets.
3. Choose how filenames should be split or parsed.
4. Name the variables you want to create.
5. Continue to preview before writing anything to OMERO.

Use stable variable names such as `sample`, `condition`, `channel`, or `time`
when the metadata will be searched or reused later.

## Preview and Apply

Review the preview table carefully. It shows what values will be written for
each image.

If the preview is wrong, go back and adjust the separator, regex, or variable
order. Apply metadata only when the preview matches the filenames.

## Variable Sets

Save a variable set when you use the same filename pattern repeatedly. Reuse it
for later datasets to keep metadata consistent.

## AI-Assisted Parsing

AI parsing is optional. Use it to suggest a filename pattern, then verify the
preview yourself before applying metadata. You can save your own provider keys
in settings.

## Deleting Metadata

- `Delete plugin annotations` removes metadata created by this plugin.
- `Delete all annotations` removes all selected key-value annotations from the
  target images.

Use deletion only after checking the selected project, datasets, and images.

## If Something Looks Wrong

- No projects or datasets: check that your OMERO account can access them.
- Wrong preview values: adjust the parser and preview again.
- Job failed: reduce the selected scope and retry after reading the message.
- AI suggestions are poor: use manual parsing or clearer custom instructions.
