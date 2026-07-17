const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("novflowDesktop", {
  platform: process.platform,
});
