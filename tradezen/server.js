const express = require("express");
const path = require("path");

const app = express();

app.use(express.json());

// Simple in-memory login check
const USER = "admin";
const PASS = "Trade123";

let isLoggedIn = false;

// Serve login page first
app.get("/", (req, res) => {
  if (!isLoggedIn) {
    return res.sendFile(path.join(__dirname, "public/login.html"));
  }
  res.sendFile(path.join(__dirname, "public/index.html"));
});

// Login API
app.post("/login", (req, res) => {
  const { username, password } = req.body;

  if (username === USER && password === PASS) {
    isLoggedIn = true;
    return res.sendStatus(200);
  }
  res.sendStatus(401);
});

// Serve other static files
app.use(express.static(path.join(__dirname, "public")));

app.listen(3000, () => console.log("Running..."));