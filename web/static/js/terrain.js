/* Real ground: USGS aerial imagery and elevation.

   Tiles come through this origin's own /api/tile proxy, so the content
   security policy stays img-src 'self' and the visitor's browser never talks
   to a third party. The server makes that request instead, which the privacy
   page states.

   The tiles are composited once into an offscreen canvas covering a known
   patch of ground in metres, and the renderer samples from it. Compositing
   once means panning and playback cost nothing extra. */

(function () {
  "use strict";

  var METRES_PER_DEG_LAT = 111320.0;

  /* One aerial photograph covering the whole run, rather than a grid of tiles.

     The tile service tops out at zoom 16, which is 1.77 m per pixel, and
     asking for anything above it returns 404 for every tile. That is what made
     the ground stay plain: nine failed requests and no imagery. NAIP is 0.3 m
     at source and one request covers exactly the ground needed, so the mapping
     from field coordinates to pixels is exact instead of reconstructed. */
  function loadFieldImage(lat, lon, headingDeg, travelMetres) {
    var psi = headingDeg * Math.PI / 180;
    var travel = Math.max(60, travelMetres || 180);

    // Centre the photograph on the middle of the run so its resolution is
    // spent where the machine actually goes.
    var mid = travel / 2;
    var mpdLon = METRES_PER_DEG_LAT * Math.max(0.05, Math.cos(lat * Math.PI / 180));
    var midLat = lat + (mid * Math.cos(psi)) / METRES_PER_DEG_LAT;
    var midLon = lon + (mid * Math.sin(psi)) / mpdLon;

    var half = Math.min(900, travel * 0.62 + 55);

    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        resolve({
          image: img,
          pixels: img.naturalWidth || 1024,
          halfMetres: half,
          midAlong: mid,
          metresPerPixel: (2 * half) / (img.naturalWidth || 1024),
          extentM: 2 * half
        });
      };
      img.onerror = function () {
        reject(new Error("No aerial imagery is available for that location. " +
          "NAIP covers the United States only."));
      };
      img.src = "/api/field-image?lat=" + midLat.toFixed(6) +
        "&lon=" + midLon.toFixed(6) + "&extent=" + Math.round(half);
    });
  }

  window.GuidanceTerrain = {
    /* Ask the server what the ground does at a location. */
    readField: function (lat, lon, heading, extent) {
      return fetch("/api/field", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ lat: lat, lon: lon, heading_deg: heading, extent_m: extent || 60 })
      }).then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) { throw new Error(body.message || "Could not read that field."); }
          return body;
        });
      });
    },

    /* One photograph covering the run. */
    loadImagery: function (lat, lon, headingDeg, travelMetres) {
      return loadFieldImage(lat, lon, headingDeg, travelMetres);
    },

    /* Model coordinates to image pixels. The line runs along model x, so the
       heading rotates model space into east and north, measured from the
       centre of the photograph rather than from the start of the run. */
    mapper: function (patch, headingDeg) {
      var psi = headingDeg * Math.PI / 180;
      var sinp = Math.sin(psi), cosp = Math.cos(psi);
      var half = patch.pixels / 2, mpp = patch.metresPerPixel;
      return function (x, y) {
        var dx = x - patch.midAlong;
        var east = dx * sinp - y * cosp;
        var north = dx * cosp + y * sinp;
        return [half + east / mpp, half - north / mpp];
      };
    },

    parseLatLon: function (text) {
      var m = String(text).split(/[,\s]+/).filter(function (s) { return s.length; });
      if (m.length !== 2) { return null; }
      var lat = parseFloat(m[0]), lon = parseFloat(m[1]);
      if (!isFinite(lat) || !isFinite(lon)) { return null; }
      if (lat < -90 || lat > 90 || lon < -180 || lon > 180) { return null; }
      return { lat: lat, lon: lon };
    }
  };
})();
