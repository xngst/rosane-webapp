//copy url to clipboard
document.getElementById('copyUrlButton').addEventListener('click', function() {
const currentUrl = window.location.href;
navigator.clipboard.writeText(currentUrl)
    .then(() => {
        alert('Megvan, elkaptad!');
    })
    .catch(err => {
        console.error('Failed to copy URL: ', err);
        alert('Sajnos nem sikerült a másolás!');
    });
});

