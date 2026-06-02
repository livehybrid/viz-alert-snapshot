/*
 * home.jsx — Webpack entry. Mounts the config UI inside the Splunk page chrome
 * (header + app nav) with the user's theme, via @splunk/react-page's layout().
 * This is what gives the Splunk look (nav bar, themed background) — a bare
 * ThemeProvider + custom div does not.
 */
import React from 'react';
import layout from '@splunk/react-page';
import { getUserTheme } from '@splunk/splunk-utils/themes';
import App from './App';

getUserTheme()
    .then((theme) => {
        layout(<App />, { theme, pageTitle: 'Visual Alerts' });
    })
    .catch((e) => {
        const el = document.createElement('span');
        el.textContent = String(e);
        document.body.appendChild(el);
    });
