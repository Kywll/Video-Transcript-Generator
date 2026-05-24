import { supabase } from "../api/supabase";

function LoginButton() {

    const login = async () => {
        await supabase.auth.signInWithOAuth({
            provider: "google"
        });
    };

    return (
        <button
            className="btn btn-outline-light"
            onClick={login}
        >
            Login with Google
        </button>
    );
}

export default LoginButton;