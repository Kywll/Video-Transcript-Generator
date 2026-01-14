function Transcript({ transcript, onWordClick}) {
    if (!transcript) return null;

    return (
        <>
            <h2>Transcript (click a word)</h2>
            <p style={{ lineHeight: "1.8" }}>
                {transcript.map((w, i) => (
                    <span
                        key={i}
                        onClick={() => onWordClick(w.start)}
                        style={{ cursor: "pointer", marginRight: "4px"}}
                    >
                        {w.word}
                    </span>
                ))}
                
            </p>
        </>
    )
}

export default Transcript;