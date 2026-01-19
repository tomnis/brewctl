import React, { useState } from 'react';

export default function FlipCard() {
  const [isFlipped, setIsFlipped] = useState(false);

  const handleFlip = () => {
    setIsFlipped(!isFlipped);
  };

  return (
    <div className="flip-card-container">
      <div
        className={`flip-card ${isFlipped ? 'flipped' : ''}`}
        onClick={handleFlip}
      >
        <div className="flip-card-front">
          <h2>Front Side</h2>
          <p>Click me to flip!</p>
        </div>
        <div className="flip-card-back">
          <h2>Back Side</h2>
          <p>This is the hidden content</p>
        </div>
      </div>
    </div>
  );
}