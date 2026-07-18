# Consulting Platform (client work)

A complete production full-stack platform, built and shipped end to end for a consulting practice.
Shown anonymously as client work.

## What's shipped
- Firebase authentication and Stripe payments, in production.
- A five-language internationalized UI.
- A modular ES6 architecture, continuous integration and deployment, and a comprehensive automated
  test suite (~486 tests).

## Design decisions
- ~486 automated tests plus CI/CD, so changes ship behind quality gates instead of manual QA.
- Firebase Auth and Stripe over hand-rolled solutions — security-critical paths run on hardened
  services; custom code goes where it differentiates.
- Five-language internationalization designed into the architecture, not bolted on afterward.

## Why it matters
Proof of production full-stack capability — authentication, payments, testing, CI/CD, and cloud
deployment — shipped for a real client.

**Stack:** JavaScript/TypeScript, modular ES6, Firebase (Auth + Firestore), Stripe, i18n (5
languages), Google Cloud Run, CI/CD.
