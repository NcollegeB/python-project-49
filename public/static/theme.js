(function () {
    'use strict';

    const STORAGE_KEY = 'brainhacker-color-theme';
    const THEMES = {
        light: {
            colorScheme: 'light',
            themeColor: '#F6F2E8',
        },
        dark: {
            colorScheme: 'dark',
            themeColor: '#151514',
        },
        grey: {
            colorScheme: 'light',
            themeColor: '#C8C8C4',
        },
        'high-contrast': {
            colorScheme: 'dark',
            themeColor: '#000000',
        },
    };

    function normaliseTheme(value) {
        return Object.prototype.hasOwnProperty.call(THEMES, value)
            ? value
            : 'light';
    }

    function readTheme() {
        try {
            return normaliseTheme(window.localStorage.getItem(STORAGE_KEY));
        } catch (_error) {
            return 'light';
        }
    }

    function applyTheme(value) {
        const theme = normaliseTheme(value);
        const settings = THEMES[theme];
        document.documentElement.dataset.theme = theme;

        const themeColor = document.querySelector('meta[name="theme-color"]');
        const colorScheme = document.querySelector('meta[name="color-scheme"]');
        if (themeColor) {
            themeColor.content = settings.themeColor;
        }
        if (colorScheme) {
            colorScheme.content = settings.colorScheme;
        }

        const select = document.getElementById('themeSelect');
        if (select) {
            select.value = theme;
        }
        return theme;
    }

    function saveTheme(theme) {
        try {
            window.localStorage.setItem(STORAGE_KEY, theme);
        } catch (_error) {
            // The selected theme still works when storage is unavailable.
        }
    }

    function bindThemeControl() {
        const select = document.getElementById('themeSelect');
        if (!select) {
            return;
        }
        select.value = normaliseTheme(document.documentElement.dataset.theme);
        select.addEventListener('change', () => {
            const theme = applyTheme(select.value);
            saveTheme(theme);
        });
    }

    applyTheme(readTheme());

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindThemeControl);
    } else {
        bindThemeControl();
    }

    window.addEventListener('storage', (event) => {
        if (event.key === STORAGE_KEY) {
            applyTheme(event.newValue);
        }
    });
}());
