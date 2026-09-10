import { getAnalytics, isSupported } from 'firebase/analytics';
import { initializeApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';
import { getStorage } from 'firebase/storage';

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || 'AIzaSyC6qEOROAuvK8clFsxkLjGpqs40G7S44H4',
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || 'hanoi-policy-makers.firebaseapp.com',
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || 'hanoi-policy-makers',
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || 'hanoi-policy-makers.firebasestorage.app',
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || '1019612666331',
  appId: import.meta.env.VITE_FIREBASE_APP_ID || '1:1019612666331:web:bb7033edaa69c9d4c76ffe',
  measurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID || 'G-LMNF2T6Q0T',
};

export const firebaseApp = initializeApp(firebaseConfig);
export const firebaseAuth = getAuth(firebaseApp);
export const googleProvider = new GoogleAuthProvider();
export const firebaseStorage = getStorage(firebaseApp);

googleProvider.setCustomParameters({ prompt: 'select_account' });

if (typeof window !== 'undefined') {
  isSupported().then((supported) => {
    if (supported) getAnalytics(firebaseApp);
  }).catch(() => undefined);
}
