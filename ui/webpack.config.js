/*
 * Self-contained build (no dependency on @splunk/webpack-configs internals):
 * babel-loader + @splunk/babel-preset, everything bundled into one page script.
 * Output → ../appserver/static/pages/home.js so the template view can load
 * /static/app/viz-alert-snapshot/pages/home.js.
 */
const path = require('path');

module.exports = {
    mode: 'production',
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
    module: {
        rules: [
            {
                test: /\.(js|jsx)$/,
                exclude: /node_modules/,
                use: {
                    loader: 'babel-loader',
                    options: { presets: ['@splunk/babel-preset'] },
                },
            },
        ],
    },
};
