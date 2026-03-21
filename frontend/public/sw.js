/**
 * Unagi Service Worker — handles Web Push notifications.
 *
 * How push notifications work:
 *   1. The browser subscribes to the push service (Google FCM, Mozilla, etc.)
 *      using our VAPID public key. The subscription has a unique endpoint URL.
 *   2. Our backend sends an encrypted HTTP POST to that endpoint URL.
 *   3. The push service delivers it to the browser, which wakes up this SW.
 *   4. The SW shows a system notification via self.registration.showNotification().
 *
 * This SW is kept minimal — all business logic lives in the backend.
 */

self.addEventListener("push", (event) => {
  let data = { title: "Unagi", body: "Tomorrow's prices are ready" };
  try {
    if (event.data) data = event.data.json();
  } catch (_) {
    /* keep defaults */
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/icon.svg",
      badge: "/icon.svg",
      tag: "unagi-price", // replaces previous notification so you don't get spammed
      renotify: true, // still vibrate/sound even when replacing
      data: { url: data.url ?? "/" },
    }),
  );
});

// Open / focus the app when the user taps the notification
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url ?? "/";
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windows) => {
        const existing = windows.find(
          (w) => new URL(w.url).pathname === target,
        );
        if (existing) return existing.focus();
        return clients.openWindow(target);
      }),
  );
});
