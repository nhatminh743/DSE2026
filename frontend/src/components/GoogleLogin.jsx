import { useEffect, useState } from 'react';
import { onAuthStateChanged, signInWithPopup, signOut, updateProfile } from 'firebase/auth';
import { getDownloadURL, ref, uploadBytes } from 'firebase/storage';
import { firebaseAuth, firebaseStorage, googleProvider } from '../firebase';
import { API_BASE } from '../staticConfig';


async function backendSession(firebaseUser) {
  const token = await firebaseUser.getIdToken();
  const response = await fetch(`${API_BASE}/api/auth/firebase`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Firebase sign-in failed');
  return { ...payload, session_token: token };
}

export default function GoogleLogin({ auth, onAuthChange }) {
  const [error, setError] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [displayName, setDisplayName] = useState('');
  const [avatar, setAvatar] = useState(null);
  const [saving, setSaving] = useState(false);
  const [accountError, setAccountError] = useState('');
  const user = auth?.user;

  useEffect(() => onAuthStateChanged(firebaseAuth, async (firebaseUser) => {
    if (!firebaseUser) {
      sessionStorage.removeItem('firebase_session');
      onAuthChange(null);
      return;
    }
    try {
      const session = await backendSession(firebaseUser);
      sessionStorage.setItem('firebase_session', JSON.stringify(session));
      onAuthChange(session);
    } catch (requestError) {
      setError(requestError.message);
    }
  }), [onAuthChange]);

  const login = async () => {
    setSigningIn(true);
    setError('');
    try {
      await signInWithPopup(firebaseAuth, googleProvider);
    } catch (requestError) {
      setError(requestError.message || 'Google sign-in failed');
    } finally {
      setSigningIn(false);
    }
  };

  const logout = async () => {
    await signOut(firebaseAuth);
    sessionStorage.removeItem('firebase_session');
    sessionStorage.removeItem('google_session');
    setAccountOpen(false);
    onAuthChange(null);
  };

  const openAccount = () => {
    setDisplayName(user?.name || '');
    setAvatar(null);
    setAccountError('');
    setAccountOpen(true);
  };

  const saveAccount = async (event) => {
    event.preventDefault();
    const firebaseUser = firebaseAuth.currentUser;
    if (!firebaseUser) return;
    setSaving(true);
    setAccountError('');
    try {
      let avatarUrl = user?.picture || firebaseUser.photoURL;
      if (avatar) {
        const extension = avatar.name.split('.').pop()?.toLowerCase() || 'jpg';
        const avatarReference = ref(firebaseStorage, `avatars/${firebaseUser.uid}/profile.${extension}`);
        await uploadBytes(avatarReference, avatar, { contentType: avatar.type });
        avatarUrl = await getDownloadURL(avatarReference);
      }
      await updateProfile(firebaseUser, { displayName: displayName.trim(), photoURL: avatarUrl });
      const token = await firebaseUser.getIdToken(true);
      const body = new FormData();
      body.append('display_name', displayName.trim());
      if (avatarUrl) body.append('avatar_url', avatarUrl);
      const response = await fetch(`${API_BASE}/api/account/profile`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || 'Could not update your account');
      const session = { ...payload, session_token: token };
      sessionStorage.setItem('firebase_session', JSON.stringify(session));
      onAuthChange(session);
      setAccountOpen(false);
    } catch (requestError) {
      setAccountError(requestError.message);
    } finally {
      setSaving(false);
    }
  };

  if (!user) return <div className="relative shrink-0"><button type="button" onClick={login} disabled={signingIn} className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50">{signingIn ? 'Signing in...' : 'Sign in with Google'}</button>{error && <div className="absolute right-0 top-11 z-50 w-72 rounded-lg border border-red-200 bg-white p-2 text-xs text-red-700 shadow-lg">{error}</div>}</div>;

  return <>
    <button type="button" onClick={openAccount} className="flex items-center gap-2 rounded-xl border border-transparent px-2 py-1 hover:border-gray-200 hover:bg-gray-50" title="Open account center">{user.picture ? <img src={user.picture} alt="" referrerPolicy="no-referrer" className="h-8 w-8 rounded-full object-cover" /> : <span className="grid h-8 w-8 place-items-center rounded-full bg-blue-100 text-sm font-semibold text-blue-700">{(user.name || user.email || '?')[0].toUpperCase()}</span>}<span className="hidden max-w-36 truncate text-xs sm:block">{user.name}</span></button>
    {accountOpen && <div className="fixed inset-0 z-[100] grid place-items-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-labelledby="account-center-title"><form onSubmit={saveAccount} className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"><div className="mb-5 flex items-start justify-between gap-4"><div><h2 id="account-center-title" className="text-xl font-semibold">Account center</h2><p className="mt-1 text-sm text-gray-500">Managed by Firebase Authentication.</p></div><button type="button" onClick={() => setAccountOpen(false)} className="rounded-lg px-2 py-1 text-xl text-gray-400 hover:bg-gray-100" aria-label="Close">×</button></div><div className="mb-4 text-sm text-gray-500">{user.email}</div><label className="mb-4 block text-sm font-medium text-gray-700">Display name<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required maxLength={80} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 font-normal" /></label><label className="mb-4 block text-sm font-medium text-gray-700">Profile picture<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setAvatar(event.target.files?.[0] || null)} className="mt-1 block w-full rounded-lg border border-gray-300 p-2 text-sm font-normal" /><span className="mt-1 block text-xs font-normal text-gray-500">PNG, JPEG, or WebP; maximum 3 MB.</span></label>{accountError && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{accountError}</div>}<div className="flex justify-between gap-2"><button type="button" onClick={logout} className="rounded-lg border border-red-200 px-4 py-2 text-sm text-red-700">Log out</button><button type="submit" disabled={saving || !displayName.trim()} className="rounded-lg bg-[#1a73e8] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{saving ? 'Saving...' : 'Save changes'}</button></div></form></div>}
  </>;
}
