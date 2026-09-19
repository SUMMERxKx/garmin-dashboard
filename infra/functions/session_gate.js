// The front door. Runs at the CloudFront edge on every request, before anything else.
//
// WHAT IT DOES
// ------------
// Lets through the handful of things needed to sign in, and for everything else demands
// a valid session cookie. No cookie means a redirect to the login page, except for API
// calls, which get a 401 so the dashboard's own code can react rather than being handed
// a page of HTML where it expected JSON.
//
// The cookie is `<expiry>.<signature>`. The signature is an HMAC over the expiry, made
// with a secret this function reads from a CloudFront KeyValueStore and the API signs
// with from its environment. So there is no session list anywhere: the cookie carries its
// own expiry, and the signature is what stops anyone editing it.
//
// WHY THE CHECK IS HERE AND NOT IN THE APP
// ----------------------------------------
// Because it has to cover the static files too. A check inside the React app would run
// only after the browser had already downloaded the React app. Here, nothing behind the
// door is served at all until the cookie is valid.
//
// FAIL CLOSED
// -----------
// Every path that is not an explicit allow, and every error including an unreadable
// store, ends in a redirect or a 401.

import cf from 'cloudfront';
import crypto from 'crypto';

// The key the signing secret is stored under, matching `infra/stacks/app_stack.py`.
const SECRET_KEY = 'session-secret';

// The cookie's name, matching `backend/api/auth.py`.
const COOKIE_NAME = 'session';

// Reachable without signing in: the login page itself, the endpoint it posts to, and the
// favicon, which the browser asks for on the login page. Everything else is behind the
// door. Kept to exact matches rather than prefixes so a path like `/login.html/../app.js`
// cannot sneak past.
const PUBLIC_PATHS = ['/login.html', '/api/login', '/favicon.svg'];

const kvs = cf.kvs();

function redirectToLogin(uri) {
    // Remember where they were aiming, so a bookmark deep into the dashboard still lands
    // there after signing in. Only the path, never a full URL -- the login page checks
    // that it starts with a single slash before using it.
    const next = encodeURIComponent(uri);

    return {
        statusCode: 302,
        statusDescription: 'Found',
        headers: {
            'location': { value: '/login.html?next=' + next },
            'cache-control': { value: 'no-store' },
        },
    };
}

function unauthorizedJson() {
    return {
        statusCode: 401,
        statusDescription: 'Unauthorized',
        headers: {
            'content-type': { value: 'application/json' },
            'cache-control': { value: 'no-store' },
        },
        body: '{"detail":"Not signed in."}',
    };
}

function cookieIsValid(value, secret, nowSeconds) {
    const parts = value.split('.');

    if (parts.length !== 2) {
        return false;
    }

    const payload = parts[0];
    const offered = parts[1];

    const expected = crypto.createHmac('sha256', secret).update(payload).digest('hex');

    if (offered !== expected) {
        return false;
    }

    const expiresAt = parseInt(payload, 10);

    // `parseInt` answers NaN for anything unparseable, and every comparison with NaN is
    // false -- so this also covers a payload that is not a number at all.
    return nowSeconds < expiresAt;
}

async function handler(event) {
    const request = event.request;
    const uri = request.uri;

    if (PUBLIC_PATHS.indexOf(uri) !== -1) {
        return request;
    }

    const isApiCall = uri.indexOf('/api/') === 0;

    const cookie = request.cookies[COOKIE_NAME];

    if (!cookie || !cookie.value) {
        return isApiCall ? unauthorizedJson() : redirectToLogin(uri);
    }

    let secret;

    try {
        secret = await kvs.get(SECRET_KEY);
    } catch (error) {
        // The secret has not been written yet, or the store is unreachable. Nobody gets
        // in, which is the correct state for a door whose lock is not fitted.
        return isApiCall ? unauthorizedJson() : redirectToLogin(uri);
    }

    const nowSeconds = Math.floor(Date.now() / 1000);

    if (!cookieIsValid(cookie.value, secret, nowSeconds)) {
        return isApiCall ? unauthorizedJson() : redirectToLogin(uri);
    }

    return request;
}
