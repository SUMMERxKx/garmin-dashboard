// The front door. Runs at the CloudFront edge on every single request, before anything
// else, and decides whether the request is allowed to continue.
//
// WHY THIS RATHER THAN A LOGIN PAGE
// ---------------------------------
// The requirement was "only I can open it, and don't build a login system". HTTP Basic
// Auth is the one mechanism where the BROWSER is the login page: answer a 401 with a
// `WWW-Authenticate: Basic` header and every browser shows its own username and password
// box, remembers the answer for the site, and sends it automatically from then on. No
// session, no cookie, no user table, no tokens to expire. About forty lines, most of
// which are comments.
//
// It is one shared credential, which is exactly right for one person and exactly wrong
// for two. The day somebody else needs in, this gets replaced by Cognito.
//
// WHERE THE PASSWORD LIVES
// ------------------------
// Not in this file, because this file is in a public repository. It is in a CloudFront
// KeyValueStore -- a tiny key-value store that lives at the edge next to the function --
// and is written there by the AWS CLI after the deploy. The code only knows the key name.
//
// FAIL CLOSED
// -----------
// Every path that is not an exact credential match returns 401, including the case where
// the store cannot be read at all. A guard that lets everyone through when it breaks is
// not a guard.

import cf from 'cloudfront';

// The key the expected credential is stored under, and the realm the browser shows in
// its prompt.
const CREDENTIAL_KEY = 'credential';
const REALM = 'Telemetry';

const kvs = cf.kvs();

function unauthorized() {
    return {
        statusCode: 401,
        statusDescription: 'Unauthorized',
        headers: {
            // This header is what makes the browser draw its password box. Without it the
            // viewer just sees a bare 401 page and has no way to authenticate.
            'www-authenticate': { value: 'Basic realm="' + REALM + '", charset="UTF-8"' },
            'cache-control': { value: 'no-store' },
        },
    };
}

async function handler(event) {
    const request = event.request;

    // CloudFront lowercases every header name, so this is `authorization` and never
    // `Authorization`.
    const offered = request.headers.authorization;

    if (!offered || !offered.value) {
        return unauthorized();
    }

    let expected;

    try {
        expected = await kvs.get(CREDENTIAL_KEY);
    } catch (error) {
        // The key has not been written yet, or the store is unreachable. Deny.
        return unauthorized();
    }

    if (offered.value !== expected) {
        return unauthorized();
    }

    // Authenticated. The request is returned UNMODIFIED, deliberately.
    //
    // An earlier version deleted the Authorization header here, reasoning that it would
    // otherwise collide with the signature CloudFront adds for the IAM-protected function
    // URL. That was unnecessary and possibly harmful: the credential never reaches an
    // origin anyway, because the origin request policy for /api/* forwards only
    // `content-type` and `accept`. The policy is the thing that decides what is
    // forwarded, and the thing CloudFront consults when deciding whether to sign.
    //
    // Leaving the request untouched keeps this function to one job -- say yes or no --
    // and keeps it out of the way of the signing that happens after it.
    return request;
}
