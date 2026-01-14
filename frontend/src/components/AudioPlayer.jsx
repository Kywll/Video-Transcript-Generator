import { forwardRef } from "react";

const AudioPlayer = forwardRef(({ src }, ref) => {
    if (!src) return null;

    return (
        <>
            <h2>Audio</h2>
            <audio ref={ref} controls src={src} />
        </>
    );
});

export default AudioPlayer;