const express = require("express");
const path = require("path");

const stockRoutes = require("./routes/stockRoute");
const adminRoutes = require("./routes/adminRoute");

const app = express();

app.use(express.json());

app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "public/index.html"));
});

// 👉 Plug routes — admin must be before stock so /api/admin/* isn't consumed by stockRoutes
app.use("/api/admin", adminRoutes);
app.use("/api", stockRoutes);

// Static files
app.use(express.static(path.join(__dirname, "public")));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Running on ${PORT}`));