# Publicable assets

Place source images and office documents used by the paper or presentation in
this directory. Remove embedded author, location, camera and editing metadata
before committing them:

```sh
make clean-assets
```

Office Open XML documents are cleaned with the Python standard library, and
embedded raster images are passed through [ExifTool](https://exiftool.org/).
PDF metadata is removed with ExifTool before qpdf rewrites the file so deleted
objects cannot remain in an incremental update. The cleaner stops before
changing a selected file when a required tool is unavailable.
