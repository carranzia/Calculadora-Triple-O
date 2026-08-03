const express = require("express");
const cors = require("cors");
const QRCode = require("qrcode");
require("dotenv").config();

const app = express();

app.use(cors());
app.use(express.json());
app.use(express.static("public"));

const PORT = process.env.PORT || 3000;
const ORS_API_KEY = process.env.ORS_API_KEY;
const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_SECRET_KEY = process.env.SUPABASE_SECRET_KEY;
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD;
const BASE_URL = process.env.BASE_URL || `http://localhost:${PORT}`;

console.log("ORS key loaded:", !!ORS_API_KEY);
console.log("Supabase configured:", !!(SUPABASE_URL && SUPABASE_SECRET_KEY));

async function sb(method, table, body = null, query = "") {
  const url = `${SUPABASE_URL}/rest/v1/${table}${query}`;
  const res = await fetch(url, {
    method,
    headers: {
      apikey: SUPABASE_SECRET_KEY,
      Authorization: `Bearer ${SUPABASE_SECRET_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=representation"
    },
    ...(body ? { body: JSON.stringify(body) } : {})
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || JSON.stringify(data));
  return data;
}

function requireAdmin(req, res, next) {
  const key = req.headers["x-admin-key"] || req.query.pwd;
  if (!ADMIN_PASSWORD || key !== ADMIN_PASSWORD) {
    return res.status(401).json({ error: "No autorizado" });
  }
  next();
}

function generateEventCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let code = "TRO-";
  for (let i = 0; i < 4; i++) {
    code += chars[Math.floor(Math.random() * chars.length)];
  }
  return code;
}

// --- ORS routes ---

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
        Authorization: ORS_API_KEY,
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

// --- Admin routes ---

app.post("/api/admin/evento", requireAdmin, async (req, res) => {
  try {
    const { nombre, descripcion } = req.body;
    if (!nombre) return res.status(400).json({ error: "El nombre del evento es obligatorio" });

    let codigo;
    let attempts = 0;
    while (attempts < 10) {
      codigo = generateEventCode();
      const existing = await sb("GET", "eventos", null, `?codigo=eq.${codigo}`);
      if (existing.length === 0) break;
      attempts++;
    }

    const evento = await sb("POST", "eventos", {
      codigo,
      nombre,
      descripcion: descripcion || null
    });

    const participantUrl = `${BASE_URL}/?evento=${codigo}`;
    const qrDataUrl = await QRCode.toDataURL(participantUrl, { width: 300, margin: 2 });

    res.json({ evento: evento[0], qrDataUrl, participantUrl });
  } catch (err) {
    console.error("Create event error:", err);
    res.status(500).json({ error: err.message });
  }
});

app.get("/api/admin/eventos", requireAdmin, async (req, res) => {
  try {
    const eventos = await sb("GET", "eventos", null, "?order=fecha_creacion.desc");
    const participantes = await sb("GET", "participantes", null, "?select=evento_codigo,total_kg");

    const countMap = {};
    participantes.forEach(p => {
      if (!countMap[p.evento_codigo]) countMap[p.evento_codigo] = { count: 0, totalKg: 0 };
      countMap[p.evento_codigo].count++;
      countMap[p.evento_codigo].totalKg += parseFloat(p.total_kg || 0);
    });

    const result = eventos.map(e => ({
      ...e,
      participantes: countMap[e.codigo]?.count || 0,
      totalKg: Math.round((countMap[e.codigo]?.totalKg || 0) * 100) / 100,
      participantUrl: `${BASE_URL}/?evento=${e.codigo}`
    }));

    res.json(result);
  } catch (err) {
    console.error("List events error:", err);
    res.status(500).json({ error: err.message });
  }
});

app.patch("/api/admin/evento/:codigo", requireAdmin, async (req, res) => {
  try {
    const { codigo } = req.params;
    const { activo } = req.body;
    const updated = await sb("PATCH", "eventos", { activo }, `?codigo=eq.${codigo}`);
    res.json(updated[0] || { codigo, activo });
  } catch (err) {
    console.error("Toggle event error:", err);
    res.status(500).json({ error: err.message });
  }
});

app.get("/api/admin/evento/:codigo/qr", requireAdmin, async (req, res) => {
  try {
    const { codigo } = req.params;
    const participantUrl = `${BASE_URL}/?evento=${codigo}`;
    const qrDataUrl = await QRCode.toDataURL(participantUrl, { width: 300, margin: 2 });
    res.json({ qrDataUrl, participantUrl });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// --- Public routes ---

app.get("/api/evento/:codigo", async (req, res) => {
  try {
    const { codigo } = req.params;
    const eventos = await sb("GET", "eventos", null, `?codigo=eq.${codigo}`);
    if (!eventos.length) return res.status(404).json({ error: "Evento no encontrado" });

    const evento = eventos[0];
    const participantes = await sb(
      "GET", "participantes", null,
      `?evento_codigo=eq.${codigo}&select=total_kg,emisiones_transporte_kg,emisiones_alojamiento_kg`
    );

    const count = participantes.length;
    const totalKg = participantes.reduce((sum, p) => sum + parseFloat(p.total_kg || 0), 0);
    const avgKg = count > 0 ? totalKg / count : 0;
    const totalTransporte = participantes.reduce((sum, p) => sum + parseFloat(p.emisiones_transporte_kg || 0), 0);
    const totalAlojamiento = participantes.reduce((sum, p) => sum + parseFloat(p.emisiones_alojamiento_kg || 0), 0);

    res.json({
      evento,
      stats: {
        participantes: count,
        totalKg: Math.round(totalKg * 100) / 100,
        avgKg: Math.round(avgKg * 100) / 100,
        totalTransporte: Math.round(totalTransporte * 100) / 100,
        totalAlojamiento: Math.round(totalAlojamiento * 100) / 100
      }
    });
  } catch (err) {
    console.error("Get event error:", err);
    res.status(500).json({ error: err.message });
  }
});

app.post("/api/participante/submit", async (req, res) => {
  try {
    const {
      evento_codigo, nombre, tramos, noches, categoria_hotel,
      emisiones_transporte_kg, emisiones_alojamiento_kg, total_kg
    } = req.body;

    if (!evento_codigo) return res.status(400).json({ error: "Falta el código de evento" });

    const eventos = await sb("GET", "eventos", null, `?codigo=eq.${evento_codigo}`);
    if (!eventos.length) return res.status(404).json({ error: "Evento no encontrado" });
    if (!eventos[0].activo) return res.status(403).json({ error: "Este evento ya no está activo" });

    const record = await sb("POST", "participantes", {
      evento_codigo,
      nombre: nombre || null,
      tramos: tramos || null,
      noches: noches || 0,
      categoria_hotel: categoria_hotel || "3",
      emisiones_transporte_kg: emisiones_transporte_kg || 0,
      emisiones_alojamiento_kg: emisiones_alojamiento_kg || 0,
      total_kg: total_kg || 0
    });

    res.json({ ok: true, id: record[0]?.id });
  } catch (err) {
    console.error("Submit participant error:", err);
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
