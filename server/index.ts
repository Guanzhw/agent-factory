import { createApp } from './app.js';
const port = Number(process.env.PORT ?? 3100);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('PORT must be an integer from 1024 to 65535');
const server = createApp().listen(port, '127.0.0.1', () => {
  console.log(`Agent Factory M1: http://127.0.0.1:${port}`);
  console.log('Model calls disabled. Auto-Research workflows are scheduled for M3.');
});
function stop() { server.close(() => process.exit(0)); }
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
