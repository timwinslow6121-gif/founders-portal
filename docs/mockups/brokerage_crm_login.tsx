import React, { useState, useEffect } from 'react';
import { 
  Shield, 
  Lock,
  ArrowRight,
  Info,
  CheckCircle,
  ActivitySquare
} from 'lucide-react';

export default function BrokerageLogin() {
  const [isLoading, setIsLoading] = useState(false);
  const [daysToAEP, setDaysToAEP] = useState(0);

  // Calculate days until AEP (October 15th)
  useEffect(() => {
    const today = new Date();
    const currentYear = today.getFullYear();
    let aepDate = new Date(currentYear, 9, 15); // Month is 0-indexed, 9 = October
    
    if (today > aepDate) {
      aepDate = new Date(currentYear + 1, 9, 15);
    }
    
    const diffTime = Math.abs(aepDate - today);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    setDaysToAEP(diffDays);
  }, []);

  const handleGoogleSSO = () => {
    setIsLoading(true);
    // Simulate OAuth redirect
    setTimeout(() => {
      // In production, this would be: window.location.href = '/auth/google/login'
      console.log("Redirecting to Google Auth...");
    }, 1500);
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden font-sans selection:bg-teal-200">
      
      {/* Dynamic Background */}
      <div className="absolute inset-0 bg-slate-900 z-0">
        {/* Soft animated gradient orbs to give a premium feel */}
        <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-teal-500/20 blur-[120px] rounded-full mix-blend-screen animate-pulse" style={{ animationDuration: '8s' }}></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] bg-blue-600/20 blur-[150px] rounded-full mix-blend-screen animate-pulse" style={{ animationDuration: '12s' }}></div>
      </div>

      {/* Background Grid Pattern */}
      <div className="absolute inset-0 opacity-[0.03] z-0 pointer-events-none" style={{ 
        backgroundImage: 'linear-gradient(to right, #ffffff 1px, transparent 1px), linear-gradient(to bottom, #ffffff 1px, transparent 1px)', 
        backgroundSize: '40px 40px' 
      }}></div>

      {/* Main Login Card - Glassmorphism Effect */}
      <div className="relative z-10 w-full max-w-md mx-4">
        
        {/* Agency Branding floating above card */}
        <div className="flex flex-col items-center justify-center mb-8">
          <div className="bg-gradient-to-br from-teal-400 to-blue-500 p-3 rounded-2xl shadow-lg shadow-teal-500/30 mb-4 ring-1 ring-white/20">
            <Shield className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-white drop-shadow-md">
            Founders<span className="font-light text-teal-300">Portal</span>
          </h1>
          <p className="text-slate-300 text-sm mt-2 font-medium tracking-wide uppercase">Agent Operating System</p>
        </div>

        {/* The Glass Card */}
        <div className="bg-white/10 backdrop-blur-xl border border-white/20 rounded-3xl p-8 shadow-2xl relative overflow-hidden">
          
          {/* Subtle shine effect on card */}
          <div className="absolute top-0 left-[-100%] w-[200%] h-full bg-gradient-to-r from-transparent via-white/5 to-transparent skew-x-[-45deg] pointer-events-none"></div>

          <div className="text-center mb-8">
            <h2 className="text-xl font-semibold text-white mb-2">Welcome Back</h2>
            <p className="text-slate-300 text-sm">Sign in to access your dashboard and commissions.</p>
          </div>

          {/* Primary Action - Google SSO */}
          <div className="space-y-6">
            <button 
              onClick={handleGoogleSSO}
              disabled={isLoading}
              className="w-full relative group flex items-center justify-center gap-3 bg-white text-slate-800 font-semibold py-4 px-4 rounded-xl transition-all duration-300 shadow-lg hover:shadow-xl hover:bg-slate-50 disabled:opacity-90 disabled:cursor-wait"
            >
              {isLoading ? (
                <>
                  <div className="w-5 h-5 border-2 border-teal-500 border-t-transparent rounded-full animate-spin"></div>
                  <span className="text-teal-600">Authenticating...</span>
                </>
              ) : (
                <>
                  <svg className="w-5 h-5 transition-transform group-hover:scale-110" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                  </svg>
                  <span className="tracking-wide">Sign in with Google</span>
                  <ArrowRight className="w-4 h-4 absolute right-4 opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all text-slate-400" />
                </>
              )}
            </button>
            
            {/* Domain Restriction Badge */}
            <div className="flex items-center justify-center gap-2 text-xs font-medium bg-slate-900/40 border border-white/10 rounded-lg py-2.5 px-4 text-slate-300">
              <Lock className="w-3.5 h-3.5 text-teal-400" />
              <span>Access restricted to <strong className="text-white">@foundersinsuranceagency.com</strong></span>
            </div>
          </div>
        </div>

        {/* Security / HIPAA Footer */}
        <div className="mt-8 text-center space-y-2">
          <p className="text-[11px] text-slate-400 flex items-center justify-center gap-1.5">
             <CheckCircle className="w-3.5 h-3.5 text-slate-500" />
             HIPAA Compliant Environment
          </p>
          <p className="text-[10px] text-slate-500 max-w-xs mx-auto leading-relaxed">
            By authenticating, you agree to agency data handling policies. All portal activity is monitored and logged for security.
          </p>
        </div>

      </div>
    </div>
  );
}