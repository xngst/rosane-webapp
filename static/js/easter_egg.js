var titkoskep = document.createElement('img');
titkoskep.setAttribute('src', '../static/img/easter_egg.jpg');

var titkoslink = document.createElement('a');
titkoslink.setAttribute('href', '#');
titkoslink.textContent = 'titkos link';
titkoslink.classList.add('hidden-link');

document.addEventListener('selectionchange', function() {
    var selection = document.getSelection();
    var selectedText = selection ? selection.toString() : null;
    var mainbox = document.getElementById('mainbox');

    if (['RÓZSA SÁNDOR', 'RÓSÁNÉKATÉKA', 'viccpárt'].includes(selectedText)) {
        mainbox.appendChild(titkoskep);
        titkoslink.style.display = 'block';
        mainbox.appendChild(titkoslink);
    } else {
        if (titkoskep.parentNode) {
            mainbox.removeChild(titkoskep);
        }
        titkoslink.style.display = 'none';
    }
});
