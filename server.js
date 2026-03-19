const express = require("express");
const cors = require("cors");
require("dotenv").config();

const app = express();

app.use(cors());
app.use(express.json());
app.use(express.static("public"));

const PORT = process.env.PORT || 3000;
const ORS_API_KEY = process.env.ORS_API_KEY;

console.log("ORS key loaded:", !!ORS_API_KEY);

app.get("/api/geocode", async (req, res) => {
  try {
    const text = req.query.text;

    if (!text) {
      return res.status(400).json({ error: "Missing text parameter" });
    }

    if (!ORS_API_KEY) {
      return res.status(500).json({ error: "ORS_API_KEY no configurada en el servidor" });
    }

    const url = `https://api.openrouteservice.org/geocode/search?api_key=${ORS_API_KEY}&text=${encodeURIComponent(text)}&size=5`;

    const response = await fetch(url);
    const data = await response.json();

    if (!response.ok) {
      console.error("Geocode API error:", data);
      return res.status(response.status).json(data);
    }

    res.json(data);
  } catch (error) {
    console.error("Geocode error:", error);
    res.status(500).json({ error: "Geocode request failed" });
  }
});

app.post("/api/route", async (req, res) => {
  try {
    const { profile, coordinates } = req.body;

    if (!ORS_API_KEY) {
      return res.status(500).json({ error: "ORS_API_KEY no configurada en el servidor" });
    }

    if (!profile || !coordinates) {
      return res.status(400).json({ error: "Missing profile or coordinates" });
    }

    const url = `https://api.openrouteservice.org/v2/directions/${profile}/geojson`;

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ coordinates })
    });

    const data = await response.json();

    if (!response.ok) {
      console.error("Route API error:", data);
      return res.status(response.status).json(data);
    }

    res.json(data);

  } catch (error) {
    console.error("Route error:", error);
    res.status(500).json({ error: "Route request failed" });
  }
});

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
