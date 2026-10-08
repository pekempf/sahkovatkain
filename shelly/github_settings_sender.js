// Optional, separate Shelly Pro 3 script. Does not switch relays.
// Fill TOKEN locally in Shelly; NEVER commit a real token to GitHub.
var TOKEN = "PASTE_FINE_GRAINED_GITHUB_TOKEN_HERE";
var URL = "https://api.github.com/repos/pekempf/sahkovatkain/dispatches";
var KEYS = ["porssi", "porssi-1", "porssi-2", "porssi-3"];
var busy = false;

function sendSettings() {
  if (busy) return;
  if (TOKEN === "PASTE_FINE_GRAINED_GITHUB_TOKEN_HERE") {
    print("GitHub token not configured");
    return;
  }
  busy = true;
  var settings = {};
  function next(i) {
    if (i >= KEYS.length) {
      var body = JSON.stringify({
        event_type: "shelly_settings",
        client_payload: {settings: settings}
      });
      Shelly.call("HTTP.Request", {
        method: "POST",
        url: URL,
        headers: {
          "Authorization": "Bearer " + TOKEN,
          "Accept": "application/vnd.github+json",
          "User-Agent": "shelly-sahkovatkain",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json"
        },
        body: body,
        timeout: 20
      }, function(res, err, msg) {
        busy = false;
        if (err) print("GitHub request error:", err, msg);
        else print("GitHub dispatch HTTP:", res.code);
      });
      return;
    }
    var key = KEYS[i];
    Shelly.call("KVS.Get", {key: key}, function(res, err, msg) {
      if (err || !res || !res.value) {
        busy = false;
        print("Cannot read KVS:", key, err, msg);
        return;
      }
      settings[key] = res.value;
      next(i + 1);
    });
  }
  next(0);
}
// Send shortly after startup and hourly; the heating script is untouched.
Timer.set(60000, false, sendSettings);
Timer.set(3600000, true, sendSettings);
