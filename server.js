require('dotenv').config();
const express = require("express");
const path    = require("path");

const { initDB } = require("./db/init");

const stockRoutes      = require("./routes/stockRoute");
const adminRoutes      = require("./routes/adminRoute");
const learnRoutes      = require("./routes/learnRoute");
const adminLearnRoutes = require("./routes/adminLearnRoute");

const app = express();

app.use(express.json());

app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "public/index.html"));
});

app.use("/mgmt",       adminRoutes);
app.use("/mgmt/learn", adminLearnRoutes);
app.use("/api",       stockRoutes);
app.use("/api/learn", learnRoutes);

// Static files
app.use(express.static(path.join(__dirname, "public")));

const PORT = process.env.PORT || 3000;

// Boot: init DB first, then start listening
initDB()
  .then(() => {
    app.listen(PORT, () => console.log(`Running on ${PORT}`));
  })
  .catch(err => {
    console.error('Server failed to start — DB init error:', err.message);
    process.exit(1);
  });
