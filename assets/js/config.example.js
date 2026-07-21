/**
 * config.example.js — commit this file, NOT config.js
 *
 * Copy this to config.js and fill in your values, OR
 * run the proxy server which injects these from environment variables:
 *
 *   export WATSONX_API_KEY=...
 *   export WATSONX_PROJECT_ID=...
 *   python3 proxy.py
 */
var WATSONX_CONFIG = {
  API_KEY: "YOUR_IBM_CLOUD_API_KEY",
  PROJECT_ID: "YOUR_WATSONX_PROJECT_ID",
  MODEL_ID: "ibm/granite-3-8b-instruct",
  URL: "https://us-south.ml.cloud.ibm.com",
};
