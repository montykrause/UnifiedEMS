const express = require('express');
const cors = require('cors');
const app = express();
const port = 5001;

app.use(cors());  // Enable CORS

app.get('/', (req, res) => {
  res.send('Hello from the UnifiedEMS backend!');
});

app.listen(port, () => {
  console.log(`Server running on http://localhost:${port}`);
});