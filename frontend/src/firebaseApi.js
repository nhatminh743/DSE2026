import { firebaseAuth } from './firebase';

export async function firebaseAuthorizedFetch(url, options = {}) {
  const user = firebaseAuth.currentUser;
  if (!user) throw new Error('Sign in with Google to continue');
  const token = await user.getIdToken();
  const headers = new Headers(options.headers || {});
  headers.set('Authorization', `Bearer ${token}`);
  return fetch(url, { ...options, headers });
}
