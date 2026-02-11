import { useState, useRef } from "react";


function Transcript({ transcript, onWordClick, currentTime, mutedIndexes, onToggleMute }) {
    const [searchWord, setSearchWord] = useState("");
    const [hoveredIndex, setHoveredIndex] = useState(null);

    const holdTimeout = useRef(null);

    if (!transcript) return null;

    return (
        <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <h2>Transcript</h2>
                <small style={{ color: "#666" }}>
                    Tip: Alt + Click (Desktop) or Long Press (Mobile) to Mute/Unmute
                </small>
            </div>

            <input 
                type="text" 
                placeholder="Search word..."
                value={searchWord}
                onChange={(e) => setSearchWord(e.target.value.toLowerCase())}
                style={{ marginBottom: "1rem", padding: "0.5rem" }}
            />
            
                <div
                    className="p-3 rounded"
                    style={{
                        border: "2px solid #2a2f3a",
                        borderRadius: "10px",
                        backgroundColor: "#0b0e14",
                        lineHeight: "1.9",
                        fontSize: "1.15rem",
                    }}
                >
                {transcript.map((w, i) => {
                    const normalizedWord = w.word.toLowerCase().replace(/[\.,!?']/g, "");
                    const isSearchMatch = searchWord && normalizedWord.includes(searchWord);
                    
                    // Logic for highlights
                    const isCurrentWord = currentTime >= w.start && currentTime <= w.end;
                    const isHovered = hoveredIndex === i;

                    const isMuted = mutedIndexes.includes(i)

                    // Determine background color priority
                    let backgroundColor = "transparent";
                    if (isSearchMatch) backgroundColor = "yellow";
                    if (isHovered) backgroundColor = "lightblue";
                    if (isMuted) backgroundColor = "red"
                    if (isCurrentWord) backgroundColor = "orange";
                    
                    return (
                        <span
                            onClick={(e) => {
                                if (!e.altKey) {
                                    onWordClick(w.start);
                                }
                            }}
                            onTouchStart={() => {
                                holdTimeout.current = setTimeout(() => {
                                    onToggleMute(i);
                                }, 500);
                            }}
                            onTouchEnd={() => {
                                clearTimeout(holdTimeout.current);
                            }}
                            key={i}
                            onMouseEnter={() => setHoveredIndex(i)}
                            onMouseLeave={() => setHoveredIndex(null)}
                            style={{
                                cursor: "pointer",
                                marginRight: "4px",
                                borderRadius: "2px",
                                backgroundColor: backgroundColor,
                                transition: "background-color 0.2s ease" 
                            }}                        
                        >
                            {w.word + " "}
                        </span>
                    );
                })}
            </div>
        </>
    );
}

export default Transcript;