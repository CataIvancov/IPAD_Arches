(function (root) {
  "use strict";

  var DRIVE_FILE_ID_RE = /^[A-Za-z0-9_-]{25,128}$/;

  function normalizeDriveFileId(value) {
    if (value == null) return null;
    var text = String(value).trim();
    if (!text) return null;
    if (/[/:?#.&%<>"'\\]/.test(text)) return null;
    if (!DRIVE_FILE_ID_RE.test(text)) return null;
    return text;
  }

  function drivePreviewUrl(fileId) {
    var normalized = normalizeDriveFileId(fileId);
    if (!normalized) return null;
    return "https://drive.google.com/file/d/" + normalized + "/preview";
  }

  function driveViewUrl(fileId) {
    var normalized = normalizeDriveFileId(fileId);
    if (!normalized) return null;
    return "https://drive.google.com/file/d/" + normalized + "/view";
  }

  root.ipadDriveUrls = {
    normalizeDriveFileId: normalizeDriveFileId,
    drivePreviewUrl: drivePreviewUrl,
    driveViewUrl: driveViewUrl,
  };
})(window);
