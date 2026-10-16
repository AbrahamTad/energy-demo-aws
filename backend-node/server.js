
const express = require("express");

const app = express();
const PORT = 3001;

// Create an API endpoint for energy data
app.get("/api/energy", (req, res) => {
  res.json({
    project: "Energy Demo",
    source: "Solar",
    production: 125,
    unit: "kWh",
    status: "working"
  });
});

// Start the server
app.listen(PORT, () => {
  console.log(`API running at http://localhost:${PORT}`);
});
