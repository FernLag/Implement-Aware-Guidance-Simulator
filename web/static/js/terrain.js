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

  var TILE = 256;
  var EQUATOR = 40075016.686;

  function globalPixel(lat, lon, z) {
    var n = TILE * Math.pow(2, z);
    var x = (lon + 180) / 360 * n;
    var s = Math.sin(lat * Math.PI / 180);
    var y = (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n;
    return [x, y];
  }

  function metresPerPixel(lat, z) {
    return EQUATOR * Math.cos(lat * Math.PI / 180) / (TILE * Math.pow(2, z));
  }

  /* Load a 3 by 3 block of tiles around a point and composite them. */
  function loadPatch(lat, lon, zoom) {
    var n = Math.pow(2, zoom);
    var gp = globalPixel(lat, lon, zoom);
    var tx = Math.floor(gp[0] / TILE), ty = Math.floor(gp[1] / TILE);

    var canvas = document.createElement("canvas");
    canvas.width = TILE * 3;
    canvas.height = TILE * 3;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#9C8F76";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    var pending = [];
    for (var dx = -1; dx <= 1; dx++) {
      for (var dy = -1; dy <= 1; dy++) {
        (function (dx, dy) {
          var X = tx + dx, Y = ty + dy;
          if (X < 0 || Y < 0 || X >= n || Y >= n) { return; }
          pending.push(new Promise(function (resolve) {
            var img = new Image();
            img.onload = function () {
              ctx.drawImage(img, (dx + 1) * TILE, (dy + 1) * TILE);
              resolve(true);
            };
            // A missing tile leaves the fallback colour rather than failing
            // the whole patch: partial coverage is better than none.
            img.onerror = function () { resolve(false); };
            img.src = "/api/tile/" + zoom + "/" + X + "/" + Y;
          }));
        })(dx, dy);
      }
    }

    var originU = gp[0] - (tx - 1) * TILE;
    var originV = gp[1] - (ty - 1) * TILE;
    var mpp = metresPerPixel(lat, zoom);

    return Promise.all(pending).then(function (results) {
      var loaded = results.filter(Boolean).length;
      return {
        canvas: canvas,
        originU: originU,
        originV: originV,
        metresPerPixel: mpp,
        zoom: zoom,
        tilesLoaded: loaded,
        tilesRequested: results.length,
        extentM: canvas.width * mpp
      };
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

    /* Imagery covering the run, at a zoom that fits the distance travelled. */
    loadImagery: function (lat, lon, travelMetres) {
      var zoom = travelMetres > 260 ? 17 : 18;
      return loadPatch(lat, lon, zoom);
    },

    /* Model coordinates to texture pixels. The AB line runs along model x, so
       the heading rotates model space into east and north before sampling. */
    mapper: function (patch, headingDeg) {
      var psi = headingDeg * Math.PI / 180;
      var sinp = Math.sin(psi), cosp = Math.cos(psi);
      return function (x, y) {
        var east = x * sinp - y * cosp;
        var north = x * cosp + y * sinp;
        return [patch.originU + east / patch.metresPerPixel,
                patch.originV - north / patch.metresPerPixel];
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
