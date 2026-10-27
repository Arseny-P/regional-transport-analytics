import React from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';

import './styles/index.css';
import 'leaflet/dist/leaflet.css';
import './leafletIcons';

if (import.meta.env.DEV && import.meta.env.VITE_API_MOCKS === 'true') {
  const { worker } = await import('./mocks/browser');
  await worker.start({ onUnhandledRequest: 'bypass' });
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
