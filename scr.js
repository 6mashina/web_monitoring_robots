const ws = new WebSocket('ws://localhost:8765');
const img = document.getElementById('video-feed');

ws.onmessage = function(event) {
    img.src = 'data:image/jpeg;base64,' + event.data;
};

ws.onerror = function(error) {
    console.error('WebSocket error:', error);
};
console.log("sas");