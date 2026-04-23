const express = require("express");
const path = require("path");

const stockRoutes = require("./routes/stockRoute");

const app = express();

app.use(express.json());

// LOGIN LOGIC (keep as is)
const USER = "admin";
const PASS = "Trade123";
let isLoggedIn = false;

app.get("/", (req, res) => {
  if (!isLoggedIn) {
    return res.sendFile(path.join(__dirname, "public/login.html"));
  }
  res.sendFile(path.join(__dirname, "public/index.html"));
});

app.post("/login", (req, res) => {
  const { username, password } = req.body;

  if (username === USER && password === PASS) {
    isLoggedIn = true;
    return res.sendStatus(200);
  }
  res.sendStatus(401);
});

// 👉 Plug routes
app.use("/api", stockRoutes);

// Static files
app.use(express.static(path.join(__dirname, "public")));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Running on ${PORT}`));