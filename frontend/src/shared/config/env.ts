const apiUrl = import.meta.env.VITE_API_URL;

if (!apiUrl) throw new Error('VITE_API_URL is not set, copy .env.example to .env');

export const API_URL = apiUrl.replace(/\/+$/, '');
