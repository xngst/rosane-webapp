document.addEventListener('DOMContentLoaded', () => {
    const lightModeToggle = document.getElementById('light-mode-toggle');
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const body = document.body;

    // Function to set the theme
    function setTheme(theme) {
        body.classList.remove('light-mode', 'dark-mode');
        body.classList.add(`${theme}-mode`);
        // Send an AJAX request to Flask to save the preference
        fetch(`/set_theme/${theme}`)
            .then(response => {
                if (!response.ok) {
                    console.error('Failed to set theme on server.');
                }
            })
            .catch(error => {
                console.error('Error sending theme preference:', error);
            });
    }

    if (body.classList.contains('dark-mode')) {

    } else {
    }


    lightModeToggle.addEventListener('click', () => {
        setTheme('light');
    });

    darkModeToggle.addEventListener('click', () => {
        setTheme('dark');
    });
});
