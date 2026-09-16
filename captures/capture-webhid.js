// Paste into the browser console on https://image.rdmctmzt.com/ BEFORE
// connecting the keyboard. Logs every HID output report in the same
// "<reportId>:<hex bytes>" format as webhid-official-tool.txt, so
// parse_capture.py and replay.py read it unchanged.
//
// When the upload has finished, run  __capSave()  to download the log.
(() => {
  if (window.__cap) { console.log("capture already installed"); return; }
  const cap = (window.__cap = []);
  const orig = HIDDevice.prototype.sendReport;
  HIDDevice.prototype.sendReport = function (reportId, data) {
    const bytes = data instanceof ArrayBuffer ? new Uint8Array(data)
      : new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join(" ");
    cap.push(reportId.toString(16).padStart(2, "0") + ":" + hex);
    return orig.apply(this, arguments);
  };
  window.__capSave = (name = "webhid-capture.txt") => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([cap.join("\n") + "\n"], { type: "text/plain" }));
    a.download = name;
    a.click();
    console.log(`saved ${cap.length} reports to ${name}`);
  };
  console.log("capture installed: connect the keyboard and upload; then run __capSave()");
})();
