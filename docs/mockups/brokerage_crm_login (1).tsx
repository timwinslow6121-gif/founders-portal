import React, { useState, useEffect } from 'react';
import { 
  Shield, 
  Lock,
  ArrowRight,
  CheckCircle,
  Calendar,
  DollarSign,
  AlertCircle,
  ChevronDown
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
      console.log("Redirecting to Google Auth...");
    }, 1500);
  };

  return (
    // Responsive Flex Container: Column on mobile, Row on desktop
    <div className="min-h-screen flex flex-col lg:flex-row font-sans bg-slate-50 selection:bg-blue-200">
      
      {/* 
        RIGHT SIDE ON DESKTOP, TOP ON MOBILE
        Using order-1 on mobile so login is always first, order-2 on desktop
      */}
      <div className="order-1 lg:order-2 w-full lg:w-1/2 flex flex-col items-center justify-center p-6 sm:p-12 relative z-10 bg-white min-h-[85vh] lg:min-h-screen shadow-2xl lg:shadow-none">
        
        <div className="w-full max-w-md mx-auto space-y-10">
          {/* Agency Branding */}
          <div className="flex flex-col items-center justify-center text-center">
            <div className="bg-gradient-to-br from-blue-600 to-blue-800 p-3 rounded-2xl shadow-lg shadow-blue-500/20 mb-5">
              <Shield className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">
              Founders <span className="font-light text-blue-600">Portal</span>
            </h1>
            <p className="text-slate-500 text-sm mt-2 font-medium tracking-wide uppercase">
              Agent Operating System
            </p>
          </div>

          { }
          {/* Login Action Container */}
          <div className="bg-slate-50 p-8 rounded-3xl border border-slate-100 shadow-sm text-center">
            <h2 className="text-xl font-semibold text-slate-800 mb-2">Welcome Back</h2>
            <p className="text-slate-500 text-sm mb-8">Sign in to access your dashboard and commissions.</p>

            <div className="space-y-4">
              <button 
                onClick={handleGoogleSSO}
                disabled={isLoading}
                className="w-full relative group flex items-center justify-center gap-3 bg-white border border-slate-200 text-slate-700 font-semibold py-3.5 px-4 rounded-xl transition-all duration-200 shadow-sm hover:shadow-md hover:bg-slate-50 hover:border-slate-300 disabled:opacity-70 disabled:cursor-wait"
              >
                {isLoading ? (
                  <>
                    <div className="w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
                    <span className="text-blue-700">Authenticating...</span>
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                    </svg>
                    <span className="tracking-wide">Sign in with Google</span>
                  </>
                )}
              </button>
              
              <div className="flex items-center justify-center gap-1.5 text-xs font-medium text-slate-500 pt-2">
                <Lock className="w-3.5 h-3.5" />
                <span>Restricted to <strong className="text-slate-700">@foundersinsuranceagency.com</strong></span>
              </div>
            </div>
          </div>

          {}
          {/* Security / HIPAA Footer */}
          <div className="text-center space-y-2 pt-8">
            <p className="text-xs text-slate-500 flex items-center justify-center gap-1.5">
               <CheckCircle className="w-4 h-4 text-emerald-500" />
               HIPAA Compliant Environment
            </p>
            <p className="text-[11px] text-slate-400 max-w-[250px] mx-auto leading-relaxed">
              All portal activity is monitored and logged. Do not access on public networks.
            </p>
          </div>
        </div>

        {/* Mobile scroll indicator - hidden on desktop */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex flex-col items-center text-slate-400 lg:hidden animate-pulse">
          <span className="text-[10px] uppercase tracking-wider mb-1">Agency Notices</span>
          <ChevronDown className="w-5 h-5" />
        </div>
      </div>

      {}
      {/* 
        LEFT SIDE ON DESKTOP, BOTTOM ON MOBILE
        Notice Board - uses order-2 on mobile, order-1 on desktop 
      */}
      <div className="order-2 lg:order-1 w-full lg:w-1/2 bg-slate-900 relative overflow-hidden flex flex-col justify-center p-6 sm:p-12 lg:p-16 border-t border-slate-800 lg:border-t-0">
        
        {/* Decorative Background Elements */}
        <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-blue-600/20 blur-[120px] rounded-full mix-blend-screen pointer-events-none"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-teal-500/10 blur-[100px] rounded-full mix-blend-screen pointer-events-none"></div>
        
        {/* Background Grid Pattern */}
        <div className="absolute inset-0 opacity-5 pointer-events-none" style={{ 
          backgroundImage: 'linear-gradient(to right, #ffffff 1px, transparent 1px), linear-gradient(to bottom, #ffffff 1px, transparent 1px)', 
          backgroundSize: '40px 40px' 
        }}></div>

        <div className="relative z-10 w-full max-w-lg mx-auto lg:mr-auto lg:ml-0 xl:mx-auto">
          
          <div className="mb-8">
            <h2 className="text-2xl font-bold text-white mb-2">Agency Notice Board</h2>
            <p className="text-slate-400 text-sm">Critical updates and schedules for your book of business.</p>
          </div>

          {}
          <div className="space-y-4">
            
            {/* Widget 1: AEP Countdown */}
            <div className="bg-white/5 border border-white/10 backdrop-blur-md rounded-2xl p-5 flex items-start gap-4 transition-transform hover:-translate-y-1 duration-300">
              <div className="bg-teal-500/20 p-3 rounded-xl">
                <Calendar className="w-6 h-6 text-teal-400" />
              </div>
              <div className="flex-1">
                <h3 className="text-white font-semibold flex items-center justify-between">
                  <span>AEP 2027 Countdown</span>
                  <span className="text-teal-400 font-bold text-lg">{daysToAEP} Days</span>
                </h3>
                <p className="text-slate-400 text-sm mt-1">Ensure all Scope of Appointments (SOAs) are prepped. Certification opens next month.</p>
              </div>
            </div>

            {/* Widget 2: Commission Run */}
            <div className="bg-white/5 border border-white/10 backdrop-blur-md rounded-2xl p-5 flex items-start gap-4 transition-transform hover:-translate-y-1 duration-300">
              <div className="bg-blue-500/20 p-3 rounded-xl">
                <DollarSign className="w-6 h-6 text-blue-400" />
              </div>
              <div>
                <h3 className="text-white font-semibold">Next Commission Payout</h3>
                <p className="text-slate-400 text-sm mt-1">The mid-month statement run will be deposited into accounts on <strong className="text-slate-200">Friday, July 17th</strong>.</p>
              </div>
            </div>

            {/* Widget 3: System Alert */}
            <div className="bg-rose-500/10 border border-rose-500/20 backdrop-blur-md rounded-2xl p-5 flex items-start gap-4">
              <div className="bg-rose-500/20 p-3 rounded-xl">
                <AlertCircle className="w-6 h-6 text-rose-400" />
              </div>
              <div>
                <h3 className="text-white font-semibold">UHC Portal Maintenance</h3>
                <p className="text-slate-400 text-sm mt-1">UnitedHealthcare is performing scheduled maintenance. Application submissions may be delayed until Sunday 2 AM EST.</p>
              </div>
            </div>

          </div>
        </div>
      </div>

    </div>
  );
}