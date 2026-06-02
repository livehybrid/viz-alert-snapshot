/* home.jsx — Webpack entry. Mounts the config UI under a Splunk theme. */
import React from 'react';
import { createRoot } from 'react-dom/client';
import { SplunkThemeProvider } from '@splunk/themes';
import App from './App';

const mount = document.createElement('div');
mount.id = 'viz-alert-root';
document.body.appendChild(mount);

createRoot(mount).render(
    <SplunkThemeProvider family="prisma" colorScheme="dark" density="comfortable">
        <App />
    </SplunkThemeProvider>
);
