# Design

Match the existing `_read` and GovernedStorage ownership convention: an existing Store connection is borrowed, locked and yielded without commit, close or replacing its context token. With no existing connection, retain engine.begin and the existing context-token cleanup. The outer transaction therefore owns material versions, publication records and command receipts together. No retry or compensating delete is added.
