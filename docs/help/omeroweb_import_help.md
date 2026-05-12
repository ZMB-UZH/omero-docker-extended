# Import Help

Use the Import plugin to upload files from your browser and import them into
OMERO with visible progress.

## Import Files

1. Choose the target project.
2. Add files or folders.
3. Review the selected items.
4. Start the upload.
5. Confirm the OMERO import.
6. Watch the status until the job finishes.

Upload and import are separate steps. A file can finish uploading before OMERO
has finished importing it.

When a project is selected, all created datasets and imported images stay inside
that project. Top-level files are placed in an automatically named dataset;
folders become datasets named from the folder path.

## Special Methods

If a special method is available, select it only when it matches your data.
Check the final status for skipped files or method-specific messages.

## OME-Zarr

OME-Zarr data may use a standard import path or a native Zarr path, depending
on the store layout and server support. After import, open the result from the
reported OMERO location.

## Progress Messages

The progress area reports upload, import, skipped-file, and failure messages.
Read the latest message before retrying.

## If Import Does Not Finish

- Confirm that the target project is correct and writable.
- Retry only the files that failed.
- Try a smaller batch if the selection is large.
- Keep the browser tab open while an upload is active.
- Ask your OMERO administrator if the same failure repeats.
