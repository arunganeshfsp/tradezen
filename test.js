const stockService = require("./services/stockService");

(async () => {
  try {
    const data = await stockService.getStockData("HDFCBANK");
    console.log(data);
  } catch (err) {
    console.error(err);
  }
})();