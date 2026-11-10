// CloudFront supplies event.viewer.ip; viewer headers never establish identity.
function handler(event) {
    var request = event.request;
    // Strip credentials supplied by any viewer. Origin custom headers overwrite them.
    delete request.headers['x-energy-contact-origin'];
    delete request.headers['x-energy-contact-ip'];
    if (request.uri === '/api/contact') {
        request.headers['x-energy-contact-ip'] = {value: event.viewer.ip};
    }
    return request;
}
