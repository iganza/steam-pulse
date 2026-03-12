// Phase 5: Reads sponsor JSON from KVS and injects x-sponsor-data header.
// Deployed as a CloudFront Function on /games/* paths.
import cf from 'cloudfront';
const kvs = cf.kvs();

async function handler(event) {
    const uri = event.request.uri;
    if (!uri.startsWith('/games/')) return event.request;
    try {
        const appid = uri.split('/')[2];
        const sponsor = await kvs.get(`sponsor_${appid}`, { format: 'json' });
        if (sponsor) {
            event.request.headers['x-sponsor-data'] = { value: JSON.stringify(sponsor) };
        }
    } catch (e) { /* no sponsor for this game */ }
    return event.request;
}
