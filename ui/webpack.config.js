/*
 * Builds the React pages into the app's appserver/static/pages/ so the
 * template-based home view can load /static/app/viz-alert-snapshot/pages/home.js.
 *
 * Uses @splunk/webpack-configs as the base (same as the CIMPlicity reference).
 */
const path = require('path');
const { merge } = require('webpack-merge');

let baseConfig = {};
try {
    // eslint-disable-next-line global-require, import/no-unresolved
    baseConfig = require('@splunk/webpack-configs/base.js').default || {};
} catch (e) {
    // base config not installed yet; entry/output below are still valid
}

module.exports = merge(baseConfig, {
    entry: {
        home: path.join(__dirname, 'src', 'home.jsx'),
    },
    output: {
        path: path.join(__dirname, '..', 'appserver', 'static', 'pages'),
        filename: '[name].js',
    },
    resolve: {
        extensions: ['.js', '.jsx'],
    },
});
