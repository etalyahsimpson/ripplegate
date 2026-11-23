'use strict';

/**
 * billing-service strict consumer contract test.
 *
 * This is a REAL executable suite (node test runner, zero third-party test
 * framework). It boots the orders-api fixture with the candidate contract,
 * performs an actual HTTP GET against it, and asserts the registered
 * dependency expectations: `customer_id` present and a non-empty string.
 * A candidate that renames the field to `account_id` makes this suite FAIL.
 *
 * Exit code 0 = all assertions held; nonzero = real assertion failure.
 * Usage: node contract.test.js /path/to/candidate.json
 */

// Resolve the producer fixture both in a checkout (../orders-api) and inside
// the controlled runner container (/suite/producer).
let { createServer } = (() => { try { return require('../orders-api/server.js'); } catch { return require('/producer/server.js'); } })();

const candidatePath = process.argv[2];
if (!candidatePath) {
  console.error('usage: node contract.test.js <candidate.json>');
  process.exit(2);
}

const fs = require('fs');
const candidateDocument = JSON.parse(fs.readFileSync(candidatePath, 'utf8'));

let failures = 0;

function assert(condition, message) {
  if (condition) {
    console.log(`PASS: ${message}`);
  } else {
    failures += 1;
    console.error(`FAIL: ${message}`);
  }
}

async function main() {
  const { server, port } = await createServer(candidateDocument);
  const base = `http://127.0.0.1:${port}`;

  const res = await fetch(`${base}/orders/order-104`, {
    headers: { accept: 'application/json' },
  });
  assert(res.status === 200, `GET /orders/order-104 returns 200 (got ${res.status})`);

  const body = await res.json();

  // billing dependency registration (registry revision 1):
  //   required_response_fields = ["customer_id", "total_cents"]
  assert(
    typeof body.customer_id === 'string' && body.customer_id.length > 0,
    `response contains customer_id as a non-empty string (got ${JSON.stringify(body.customer_id)})`,
  );
  assert(
    Number.isFinite(body.total_cents),
    `response contains numeric total_cents (got ${JSON.stringify(body.total_cents)})`,
  );

  // informational only: billing tolerates unknown optional members, but a
  // rename of customer_id itself would have failed the assertions above
  const extras = Object.keys(body).filter(
    (k) => !['id', 'customer_id', 'total_cents'].includes(k),
  );
  if (extras.length > 0) {
    console.log(`INFO: tolerating optional extra member(s): ${extras.join(', ')}`);
  }

  server.close();
  if (failures > 0) {
    console.error(`billing-service contract: ${failures} assertion(s) failed`);
    process.exit(1);
  }
  console.log('billing-service contract: all assertions passed');
  process.exit(0);
}

main().catch((err) => {
  console.error('billing-service contract: execution error', err);
  process.exit(3);
});
